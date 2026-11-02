# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

import json
import posixpath
import secrets
from urllib.parse import urlparse

import boto3
import frappe
import requests
from crm.fcrm.doctype.crm_call_log.crm_call_log import get_call_log as _crm_get_call_log
from crm.integrations.api import get_contact_by_phone_number as _crm_get_contact_by_phone_number
from crm.integrations.api import is_call_integration_enabled as _crm_is_call_integration_enabled
from frappe import _
from frappe.integrations.utils import create_request_log

OPEN_ISSUE_STATUSES = ("Open", "Replied", "On Hold")

# Sarvam's instant-outbound REST API - a single call, distinct from its
# campaign/cohort API used for bulk dialing. Auth is X-API-Key, not the
# api-subscription-key the Sarvam STT/TTS/LLM SDKs use.
SARVAM_OUTBOUND_API_BASE = "https://apps.sarvam.ai/api/outbounds/v1"

SARVAM_SETTINGS_DOCTYPE = "Sarvam Voice Agent Settings"

# @businessRule [BR-TEL-002] Required fields in the "Sarvam Outbound
# Settings" section of Sarvam Voice Agent Settings to place an outbound call
# - mirrors how CRM Twilio/Exotel Settings store their own per-workspace
# config, instead of site_config.json, so it is editable from the Desk UI
# with secrets held as Password fields.
SARVAM_OUTBOUND_REQUIRED_FIELDS = (
	"outbound_api_key",
	"webhook_secret",
	"org_id",
	"workspace_id",
	"support_connection_id",
	"support_agent_phone_number",
	"support_agent_id",
	"support_agent_version",
)


def _is_sarvam_enabled():
	"""
	Business Purpose: [BR-TEL-002] Reports Sarvam AI as configured once
	Sarvam Voice Agent Settings' outbound section is enabled, mirroring how
	CRM Twilio/Exotel Settings report their own `enabled` flag.

	Returns:
		bool: True when outbound calling is enabled for this site.
	"""
	return bool(frappe.db.get_single_value(SARVAM_SETTINGS_DOCTYPE, "enabled"))


def _is_call_logging_enabled():
	"""
	Business Purpose: [BR-TEL-004] Reports whether S3 call-logging (archiving
	recordings/transcripts from Sarvam voice agent calls) is configured,
	independently of whether outbound calling itself is enabled.

	Returns:
		bool: True when Sarvam Voice Agent Settings' Call Logging Settings
		section is enabled for this site.
	"""
	return bool(frappe.db.get_single_value(SARVAM_SETTINGS_DOCTYPE, "enable_call_logging"))


@frappe.whitelist()
def is_call_integration_enabled():
	"""
	Business Purpose: [BR-TEL-002] Extends CRM's call-integration status with
	a `sarvam` flag so the frontend can offer Sarvam AI as a calling medium
	alongside Twilio/Exotel.

	Returns:
		dict: The original CRM payload with an added `integrations.sarvam` flag.
	"""
	result = _crm_is_call_integration_enabled()
	result["integrations"]["sarvam"] = _is_sarvam_enabled()
	return result


def get_latest_open_issue_for_contact(contact_name):
	"""
	Business Purpose: [BR-TEL-001] Finds the Support ticket a caller is most
	likely calling about, so outbound Sarvam calls and inbound webhooks can
	be linked to the right Issue instead of a bare Contact.

	Args:
		contact_name (str): Name of the Contact matched from the phone number.

	Returns:
		str | None: Name of the most recently opened matching Issue, if any.
	"""
	if not contact_name:
		return None

	return frappe.db.get_value(
		"Issue",
		{"contact": contact_name, "status": ("in", OPEN_ISSUE_STATUSES)},
		"name",
		order_by="opening_date desc, creation desc",
	)


@frappe.whitelist()
def get_contact_by_phone_number(phone_number: str):
	"""
	Business Purpose: [BR-TEL-001] Enriches CRM's contact lookup with an
	`issue` key when the matched Contact has no CRM Lead/Deal but does have
	an open Support ticket.

	Args:
		phone_number (str): Raw phone number from the call payload.

	Returns:
		dict: The original CRM contact dict, with `issue` added when relevant.
	"""
	contact = _crm_get_contact_by_phone_number(phone_number)

	# @businessRule [BR-TEL-001] Lead/Deal still outrank a Support ticket -
	# only fall back to Issue once CRM itself found neither.
	if contact.get("name") and not contact.get("lead") and not contact.get("deal"):
		issue = get_latest_open_issue_for_contact(contact["name"])
		if issue:
			contact["issue"] = issue

	return contact


@frappe.whitelist()
def get_contact_lead_or_deal_from_number(number: str):
	"""
	Business Purpose: [BR-TEL-001] Resolves a phone number to the record a
	call should be linked against, adding `Issue` below `CRM Lead`/`CRM Deal`
	and above a bare `Contact` in priority.

	Args:
		number (str): Raw phone number from the call payload.

	Returns:
		tuple[str | None, str | None]: (docname, doctype) of the best match.
	"""
	contact = get_contact_by_phone_number(number)
	if not contact.get("name"):
		return None, None

	if contact.get("lead"):
		return contact["lead"], "CRM Lead"
	if contact.get("deal"):
		return contact["deal"], "CRM Deal"
	if contact.get("issue"):
		return contact["issue"], "Issue"

	return contact["name"], "Contact"


@frappe.whitelist()
def get_call_log(name: str):
	"""
	Business Purpose: [BR-TEL-001] Surfaces a linked Support ticket on the
	call log detail payload, the same way CRM surfaces `_lead`/`_deal`.

	Args:
		name (str): Name of the CRM Call Log.

	Returns:
		dict: CRM's own call log payload, with `_issue` added when the call
		references or links to an Issue the user can read.
	"""
	call = _crm_get_call_log(name)

	issue = None
	if call.get("reference_doctype") == "Issue" and call.get("reference_docname"):
		issue = call["reference_docname"]
	else:
		for link in call.get("links") or []:
			if link.get("link_doctype") == "Issue":
				issue = link.get("link_name")
				break

	if issue and frappe.has_permission("Issue", "read", issue):
		call["_issue"] = issue

	return call


def _get_sarvam_outbound_config():
	"""
	Business Purpose: [BR-TEL-002] Reads the "Sarvam Outbound Settings"
	section of Sarvam Voice Agent Settings and fails loudly, naming every
	missing field, rather than letting a partially configured integration
	fail deep inside a requests call.

	Returns:
		dict: {fieldname: value} for every field in
		SARVAM_OUTBOUND_REQUIRED_FIELDS, with `outbound_api_key` decrypted.

	Raises:
		frappe.ValidationError: If outbound calling is disabled, or any
			required field is missing.
	"""
	settings = frappe.get_cached_doc(SARVAM_SETTINGS_DOCTYPE)
	if not settings.enabled:
		frappe.throw(_("Sarvam outbound calling is not enabled"))

	password_fields = ("outbound_api_key", "webhook_secret")
	config = {
		field: (settings.get_password(field) if field in password_fields else settings.get(field))
		for field in SARVAM_OUTBOUND_REQUIRED_FIELDS
	}
	missing = [field for field, value in config.items() if not value]
	if missing:
		frappe.throw(
			_("Sarvam Voice Agent Settings is missing: {0}").format(", ".join(missing))
		)
	return config


# @businessRule [BR-TEL-004] Required fields in the "Call Logging Settings"
# section of Sarvam Voice Agent Settings to archive a call's recording and
# transcript to S3. Separate from SARVAM_OUTBOUND_REQUIRED_FIELDS since call
# logging is an independent toggle - it can be enabled without outbound
# calling, and will eventually cover inbound calls too.
CALL_LOGGING_REQUIRED_FIELDS = (
	"s3_bucket",
	"s3_region",
	"s3_access_key_id",
	"s3_secret_access_key",
	"s3_inbound_path_prefix",
	"s3_outbound_path_prefix",
)


def _get_call_logging_config():
	"""
	Business Purpose: [BR-TEL-004] Reads the "Call Logging Settings" section
	of Sarvam Voice Agent Settings and fails loudly, naming every missing
	field, rather than silently skipping an archive upload.

	Returns:
		dict: {fieldname: value} for every field in
		CALL_LOGGING_REQUIRED_FIELDS, with `s3_secret_access_key` decrypted,
		plus `s3_endpoint_url` (optional, may be empty).

	Raises:
		frappe.ValidationError: If call logging is disabled, or any required
			field is missing.
	"""
	settings = frappe.get_cached_doc(SARVAM_SETTINGS_DOCTYPE)
	if not settings.enable_call_logging:
		frappe.throw(_("Sarvam call logging is not enabled"))

	config = {
		field: (
			settings.get_password(field) if field == "s3_secret_access_key" else settings.get(field)
		)
		for field in CALL_LOGGING_REQUIRED_FIELDS
	}
	missing = [field for field, value in config.items() if not value]
	if missing:
		frappe.throw(
			_("Sarvam Voice Agent Settings is missing: {0}").format(", ".join(missing))
		)
	config["s3_endpoint_url"] = settings.get("s3_endpoint_url") or None
	return config


def _get_s3_client(config):
	"""
	Business Purpose: [BR-TEL-004] Builds a boto3 S3 client from Call Logging
	Settings, supporting AWS S3 and S3-compatible stores (MinIO, R2, ...) via
	an optional endpoint override.

	Args:
		config (dict): Output of `_get_call_logging_config()`.

	Returns:
		boto3.client: An S3 client scoped to the configured credentials.
	"""
	return boto3.client(
		"s3",
		aws_access_key_id=config["s3_access_key_id"],
		aws_secret_access_key=config["s3_secret_access_key"],
		region_name=config["s3_region"],
		endpoint_url=config["s3_endpoint_url"],
	)


def _guess_recording_extension(recording_url):
	"""
	Business Purpose: [BR-TEL-004] Keeps the archived recording's file
	extension consistent with whatever Sarvam actually served, instead of
	assuming a fixed audio format.

	Args:
		recording_url (str): The URL Sarvam's webhook gave for the recording.

	Returns:
		str: A dotted extension, e.g. ".mp3"; defaults to ".mp3" if the URL
		has none.
	"""
	if not recording_url:
		return ".mp3"
	_, suffix = posixpath.splitext(urlparse(recording_url).path)
	return suffix or ".mp3"


def _build_s3_key(path_prefix, interaction_id, campaign_id, extension):
	"""
	Business Purpose: [BR-TEL-004] Lays out archived call files predictably -
	flat under the direction's prefix, except that calls placed as part of a
	Sarvam campaign are nested one level deeper under the campaign, so a
	campaign's calls can be browsed/retrieved as a single group.

	Args:
		path_prefix (str): `s3_inbound_path_prefix` or `s3_outbound_path_prefix`.
		interaction_id (str): Sarvam's `interaction_id` for this call.
		campaign_id (str | None): Sarvam's `campaign_id`, if this call was
			placed as part of a campaign (never set by our current
			instant-outbound flow, which only does single calls - this is
			forward-looking for when campaign-based outbound is added).
		extension (str): Dotted file extension, e.g. ".mp3" or ".json".

	Returns:
		str: The S3 object key.
	"""
	prefix = f"{path_prefix}/{campaign_id}" if campaign_id else path_prefix
	return f"{prefix}/{interaction_id}{extension}"


def upload_conversation_to_s3(direction, interaction_id, campaign_id=None, recording_url=None, transcript=None):
	"""
	Business Purpose: [BR-TEL-004] Archives a Sarvam voice agent call's
	recording and transcript to S3, keyed by `interaction_id`, so they
	outlive Sarvam's own hosted URLs. Shared by both outbound and inbound
	webhook handlers - inbound call handling does not exist in this app yet,
	but this function takes `direction` so it is ready to be called from an
	inbound handler without changes here.

	Never raises: a call-logging failure must not break the caller's primary
	job of updating the CRM Call Log, so every failure is logged and
	swallowed.

	Args:
		direction (str): "inbound" or "outbound".
		interaction_id (str | None): Sarvam's interaction id. No-op if falsy,
			since there would be nothing to key the upload by.
		campaign_id (str | None): Sarvam's campaign id, if any ([BR-TEL-004]
			sub-foldering - see `_build_s3_key`).
		recording_url (str | None): Sarvam's hosted recording URL, if any.
		transcript (list | None): Sarvam's `interaction_transcript`, if any.
	"""
	if not interaction_id or not _is_call_logging_enabled():
		return

	try:
		config = _get_call_logging_config()
		client = _get_s3_client(config)
		path_prefix = config["s3_inbound_path_prefix" if direction == "inbound" else "s3_outbound_path_prefix"]

		if recording_url:
			recording = requests.get(recording_url, timeout=30)
			recording.raise_for_status()
			client.put_object(
				Bucket=config["s3_bucket"],
				Key=_build_s3_key(path_prefix, interaction_id, campaign_id, _guess_recording_extension(recording_url)),
				Body=recording.content,
			)

		if transcript:
			client.put_object(
				Bucket=config["s3_bucket"],
				Key=_build_s3_key(path_prefix, interaction_id, campaign_id, ".json"),
				Body=json.dumps(transcript, ensure_ascii=False).encode("utf-8"),
				ContentType="application/json",
			)
	except Exception:
		frappe.log_error(title="Sarvam call-logging S3 upload failed")


def _generate_verification_code():
	"""
	Business Purpose: [BR-TEL-003] A short, human-speakable code shown to the
	user who clicked "Call via Sarvam" and read back by the staff member who
	answers, so both sides confirm they are talking about the same call -
	not voicemail, not a stranger who happened to pick up the phone.

	Returns:
		str: A zero-padded 4-digit code, e.g. "0427".
	"""
	return f"{secrets.randbelow(10000):04d}"


def _get_outbound_caller_mobile(user):
	"""
	Business Purpose: [BR-TEL-003] Only a user already registered as a
	telephony agent (same gate CRM's own Twilio/Exotel make_a_call uses) may
	trigger a Sarvam outbound call at all - this is the authorization check.
	It no longer determines who gets dialed; see `_resolve_telephony_agent`
	for that, since the triggering user can now pick a different agent.

	Args:
		user (str): The Frappe user triggering the call.

	Returns:
		str | None: The user's registered mobile number, or None if the user
		is not a registered CRM Telephony Agent.
	"""
	return frappe.db.get_value("CRM Telephony Agent", {"user": user}, "mobile_no")


def _resolve_telephony_agent(telephony_agent=None):
	"""
	Business Purpose: [BR-TEL-003] Resolves which registered CRM Telephony
	Agent actually gets dialed and briefed by Sarvam. Defaults to the
	triggering user's own record, but a dispatcher who is themselves a
	registered agent ([BR-TEL-003]'s authorization check, enforced
	separately in `trigger_sarvam_call`) may route the call to a different
	registered agent instead - e.g. whichever teammate is actually free to
	take it. `CRM Telephony Agent` is autonamed `field:user`, so its `name`
	is the agent's own user id.

	Args:
		telephony_agent (str | None): Name of a CRM Telephony Agent record.
			Defaults to `frappe.session.user`'s own record.

	Returns:
		dict: {user, user_name, mobile_no} of the resolved agent.

	Raises:
		frappe.ValidationError: If the resolved agent doesn't exist or has
			no mobile number on file.
	"""
	agent_name = telephony_agent or frappe.session.user
	agent = frappe.db.get_value(
		"CRM Telephony Agent", agent_name, ["user", "user_name", "mobile_no"], as_dict=True
	)
	if not agent or not agent.mobile_no:
		frappe.throw(
			_("{0} is not registered as a CRM Telephony Agent with a mobile number.").format(agent_name)
		)
	return agent


def _get_issue_call_context(issue_name):
	"""
	Business Purpose: [BR-TEL-002] Resolves the phone number and Sarvam
	call-context variables for an Issue (Support ticket).

	Args:
		issue_name (str): Name of the Issue being called about.

	Returns:
		dict: {phone_number, record_doctype_label, record_subject,
		contact_name, record_status}. phone_number is None if unresolvable.
	"""
	issue = frappe.get_doc("Issue", issue_name)
	phone_number, contact_name = None, issue.customer
	if issue.contact:
		contact = frappe.db.get_value(
			"Contact", issue.contact, ["mobile_no", "phone", "full_name"], as_dict=True
		)
		if contact and (contact.mobile_no or contact.phone):
			phone_number, contact_name = contact.mobile_no or contact.phone, contact.full_name

	return {
		"phone_number": phone_number,
		"record_doctype_label": "Support ticket",
		"record_subject": issue.subject or "",
		"contact_name": contact_name or "",
		"record_status": issue.status or "",
	}


def _get_crm_lead_call_context(lead_name):
	"""
	Business Purpose: [BR-TEL-002] Resolves the phone number and Sarvam
	call-context variables for a CRM Lead.

	Args:
		lead_name (str): Name of the CRM Lead being called about.

	Returns:
		dict: {phone_number, record_doctype_label, record_subject,
		contact_name, record_status}. phone_number is None if unresolvable.
	"""
	lead = frappe.get_doc("CRM Lead", lead_name)
	return {
		"phone_number": lead.mobile_no or lead.phone,
		"record_doctype_label": "Sales lead",
		"record_subject": lead.organization or lead.lead_name or "",
		"contact_name": lead.lead_name or "",
		"record_status": lead.status or "",
	}


def _get_crm_deal_call_context(deal_name):
	"""
	Business Purpose: [BR-TEL-002] Resolves the phone number and Sarvam
	call-context variables for a CRM Deal, from its primary Contact.

	Args:
		deal_name (str): Name of the CRM Deal being called about.

	Returns:
		dict: {phone_number, record_doctype_label, record_subject,
		contact_name, record_status}. phone_number is None if unresolvable.
	"""
	deal = frappe.get_doc("CRM Deal", deal_name)
	phone_number, contact_name = None, None
	primary_contact = frappe.db.get_value(
		"CRM Contacts", {"parenttype": "CRM Deal", "parent": deal_name, "is_primary": 1}, "contact"
	)
	if primary_contact:
		contact = frappe.db.get_value(
			"Contact", primary_contact, ["mobile_no", "phone", "full_name"], as_dict=True
		)
		if contact and (contact.mobile_no or contact.phone):
			phone_number, contact_name = contact.mobile_no or contact.phone, contact.full_name

	return {
		"phone_number": phone_number,
		"record_doctype_label": "Sales deal",
		"record_subject": deal.organization or deal.lead_name or "",
		"contact_name": contact_name or deal.lead_name or "",
		"record_status": deal.status or "",
	}


# @businessRule [BR-TEL-002] Every doctype Sarvam calling supports - extend
# this (and the matching Client Script fixture + has_permission check below)
# to add another one, rather than hardcoding a new whitelisted method per
# doctype.
SARVAM_CALL_CONTEXT_RESOLVERS = {
	"Issue": _get_issue_call_context,
	"CRM Lead": _get_crm_lead_call_context,
	"CRM Deal": _get_crm_deal_call_context,
}


@frappe.whitelist()
def trigger_sarvam_call(reference_doctype: str, reference_name: str, telephony_agent: str | None = None):
	"""
	Business Purpose: [BR-TEL-002] [BR-TEL-003] Places an outbound Sarvam call
	about an Issue, CRM Lead or CRM Deal via Sarvam's instant-outbound REST
	API. Sarvam dials the resolved telephony agent's registered mobile first
	(the triggering user's own by default, or another registered agent if
	`telephony_agent` is given - e.g. a dispatcher routing to whoever is
	free), briefs them on the record, then immediately blind-transfers to
	the customer - so by the time the customer's phone rings, the agent is
	already live and speaks to them directly, with no AI greeting on the
	customer's side at all. Logs the attempt as a CRM Call Log so it appears
	alongside Twilio/Exotel calls (see [BR-TEL-001] for how an Issue
	reference is then resolved back from a call).

	Args:
		reference_doctype (str): One of SARVAM_CALL_CONTEXT_RESOLVERS's keys.
		reference_name (str): Name of that record to call about.
		telephony_agent (str | None): Name of a CRM Telephony Agent record to
			dial instead of the triggering user's own ([BR-TEL-003]). The
			triggering user must still themselves be a registered agent -
			this only changes who is dialed, not who may trigger the call.

	Returns:
		dict: {call_log, verification_code} - verification_code is the
		4-digit code the frontend must show the clicking user, and which
		the resolved telephony agent must read back to Sarvam before it
		transfers ([BR-TEL-003]).

	Raises:
		frappe.ValidationError: If reference_doctype isn't supported, the
			record has no resolvable phone number, `telephony_agent` doesn't
			resolve to a registered agent with a mobile number, Sarvam
			outbound calling is not configured, or the call could not be
			placed.
		frappe.PermissionError: If the user cannot read the record, or is
			not themselves a registered CRM Telephony Agent ([BR-TEL-003]).
	"""
	resolve_context = SARVAM_CALL_CONTEXT_RESOLVERS.get(reference_doctype)
	if not resolve_context:
		frappe.throw(
			_("Sarvam calling does not support {0}").format(reference_doctype), frappe.ValidationError
		)

	if not frappe.has_permission(reference_doctype, "read", reference_name):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	# @businessRule [BR-TEL-003] Triggering a Sarvam outbound call at all is
	# restricted to users already registered as a CRM Telephony Agent - the
	# same gate CRM's own Twilio/Exotel make_a_call uses. This is who may
	# trigger the call, separate from who gets dialed (resolved below).
	if not _get_outbound_caller_mobile(frappe.session.user):
		frappe.throw(
			_("You are not registered as a CRM Telephony Agent, so you cannot place outbound calls."),
			frappe.PermissionError,
		)

	agent = _resolve_telephony_agent(telephony_agent)

	context = resolve_context(reference_name)
	phone_number = context["phone_number"]
	if not phone_number:
		frappe.throw(_("{0} {1} has no contact phone number to call").format(reference_doctype, reference_name))

	config = _get_sarvam_outbound_config()
	verification_code = _generate_verification_code()

	call_log = frappe.get_doc(
		{
			"doctype": "CRM Call Log",
			"caller": agent.user,
			"type": "Outgoing",
			"status": "Initiated",
			"telephony_medium": "Sarvam",
			"from": config["support_agent_phone_number"],
			"to": phone_number,
			"reference_doctype": reference_doctype,
			"reference_docname": reference_name,
		}
	).insert(ignore_permissions=True)

	# @businessRule [BR-TEL-002] Sarvam's servers must reach this webhook over
	# the public internet, which a local/dev site_name (e.g. development.localhost)
	# never is. sarvam_webhook_base_url is a site_config.json-only escape hatch
	# (e.g. a cloudflared/ngrok tunnel URL during local testing) - deliberately
	# not on Sarvam Voice Agent Settings, since it's a site-identity concern,
	# not a Sarvam workspace one, and get_url() remains correct for production.
	webhook_base_url = frappe.conf.get("sarvam_webhook_base_url") or frappe.utils.get_url()
	webhook_url = (
		f"{webhook_base_url}/api/method/core_customizations.core_customizations."
		f"sarvam_telephony.handle_outbound_webhook?key={config['webhook_secret']}"
	)

	payload = {
		"app_config": {
			"app_id": config["support_agent_id"],
			"app_version": config["support_agent_version"],
			"connection_config": {
				"connection_id": config["support_connection_id"],
				"agent_phone_number": config["support_agent_phone_number"],
			},
			"agent_variables": {
				"record_doctype_label": context["record_doctype_label"],
				"record_name": reference_name,
				"record_subject": context["record_subject"],
				"contact_name": context["contact_name"],
				"record_status": context["record_status"],
				# @businessRule [BR-TEL-003] Both the clicking user (shown this
				# in the popup) and the staff member who answers (asked to
				# read it back by the agent) see this code, so a mismatch
				# means the wrong person picked up, not the intended call.
				"verification_code": verification_code,
				# @businessRule [BR-TEL-003] Sarvam dials the STAFF member
				# first (user_phone_number below) and briefs them, then
				# blind-transfers to transfer_to (the customer) - so by the
				# time the customer's phone rings, the staff member is
				# already live and speaks to them directly, with no AI
				# greeting on the customer's side at all.
				"transfer_to": phone_number,
			},
		},
		"user_config": {"user_phone_number": agent.mobile_no},
		"webhook_config": {
			"url": webhook_url,
			"metadata": {"call_log": call_log.name},
		},
	}

	try:
		response = requests.post(
			f"{SARVAM_OUTBOUND_API_BASE}/orgs/{config['org_id']}"
			f"/workspaces/{config['workspace_id']}/outbounds",
			json=payload,
			headers={"X-API-Key": config["outbound_api_key"]},
			timeout=30,
		)
		response.raise_for_status()
	except requests.RequestException:
		call_log.db_set("status", "Failed", update_modified=False)
		frappe.log_error(title="Sarvam outbound call failed")
		frappe.throw(_("Could not place the Sarvam outbound call. See the error log for details."))

	attempt_id = (response.json() or {}).get("attempt_id")
	if attempt_id:
		call_log.db_set("id", attempt_id, update_modified=False)

	return {"call_log": call_log.name, "verification_code": verification_code}


def _find_call_log_by_attempt(attempt_id):
	"""Match a Sarvam webhook back to the CRM Call Log it belongs to."""
	if not attempt_id:
		return None
	return frappe.db.get_value("CRM Call Log", {"id": attempt_id}, "name")


# @businessRule [BR-TEL-002] Confirmed by a real webhook delivery (2026-11-02):
# this endpoint's actual payload has a single flat `status` field, NOT the
# connectivity_status/completion_status pair documented at
# sarvam://schemas/webhook-payload for campaign webhooks - that schema does
# not describe the instant-outbound endpoint. Observed value: "busy". The
# rest of this map is a best-effort guess at the sibling values pending more
# real deliveries; anything unrecognised defaults to "Failed", not
# "Completed" - a terminal webhook with an unknown status should never be
# silently reported as a successful call.
SARVAM_STATUS_MAP = {
	"busy": "Busy",
	"no_answer": "No Answer",
	"noanswer": "No Answer",
	"failed": "Failed",
	"cancelled": "Canceled",
	"canceled": "Canceled",
	"completed": "Completed",
	"connected": "Completed",
	"in_progress": "In Progress",
	"ringing": "Ringing",
	"queued": "Queued",
	"initiated": "Initiated",
}


def _map_sarvam_call_status(status):
	"""
	Business Purpose: [BR-TEL-002] Maps Sarvam's call-outcome `status` string
	onto CRM Call Log's own `status` Select options.

	Args:
		status (str | None): Sarvam's reported outcome (e.g. "busy").

	Returns:
		str: One of CRM Call Log's status options; "Failed" for anything
		unrecognised.
	"""
	mapped = SARVAM_STATUS_MAP.get((status or "").lower().replace("-", "_"))
	if mapped:
		return mapped

	frappe.log_error(title="Unrecognised Sarvam call status", message=f"status={status!r}")
	return "Failed"


@frappe.whitelist(allow_guest=True)  # nosemgrep: guest-whitelisted-method
def handle_outbound_webhook(**kwargs):
	"""
	Business Purpose: [BR-TEL-002] Receives Sarvam's call-end webhook for an
	outbound Support call and updates the matching CRM Call Log.

	Confirmed by a real delivery (2026-11-02): this endpoint's payload is
	flatter than the documented campaign-webhook schema - a single `status`
	string instead of connectivity_status/completion_status, no
	campaign_id/cohort_id, and `metadata` nested under the echoed
	`webhook_config`, not at the top level. Every payload is logged via
	create_request_log regardless, so any further shape drift is visible and
	correctable without losing the raw payload.

	Webhook authenticity is enforced by the `key` query param (matched
	against Sarvam Voice Agent Settings' `webhook_secret`), the same workaround
	CRM's own Exotel handler uses since Sarvam, like Exotel, does not sign
	its webhook.

	Args:
		**kwargs: The webhook body, forwarded as request args by Frappe.
	"""
	key = frappe.request.args.get("key")
	webhook_secret = frappe.get_cached_doc(SARVAM_SETTINGS_DOCTYPE).get_password(
		"webhook_secret", raise_exception=False
	)
	if not key or not webhook_secret or key != webhook_secret:
		frappe.throw(_("Unauthorized request"), exc=frappe.PermissionError)

	payload = frappe.request.get_json(silent=True) or kwargs

	request_log = create_request_log(
		payload,
		request_description="Sarvam Outbound Call",
		service_name="Sarvam",
		request_headers=frappe.request.headers,
		is_remote_request=1,
	)

	try:
		metadata = (payload.get("webhook_config") or {}).get("metadata") or payload.get("metadata") or {}
		call_log_name = metadata.get("call_log") or _find_call_log_by_attempt(payload.get("attempt_id"))
		if not call_log_name:
			raise frappe.ValidationError(f"Could not match Sarvam webhook payload to a CRM Call Log: {payload}")

		call_log = frappe.get_doc("CRM Call Log", call_log_name)
		call_log.status = _map_sarvam_call_status(payload.get("status"))
		if payload.get("duration") is not None:
			call_log.duration = payload.get("duration")
		if payload.get("recording_url"):
			call_log.recording_url = payload.get("recording_url")
		call_log.save(ignore_permissions=True)

		# @businessRule [BR-TEL-002] interaction_transcript is turn-by-turn
		# STT/TTS from the AI's OWN side of the call only - after the blind
		# call_transfer hands off to the human agent, Sarvam's agent (and its
		# STT) is no longer confirmed to be in the audio path, so this is
		# likely just the brief greeting, not the human-customer conversation.
		# Logged as a comment (CRM Call Log has no transcript field) so it is
		# visible without asserting it is complete.
		transcript = payload.get("interaction_transcript")
		if transcript:
			transcript_text = "\n".join(
				f"{turn.get('role', '?')}: {turn.get('en_text', '')}" for turn in transcript
			)
			call_log.add_comment("Comment", _("Sarvam transcript (AI side only):\n{0}").format(transcript_text))

		# @businessRule [BR-TEL-004] Archives the recording/transcript to S3
		# if Call Logging Settings is enabled - a no-op otherwise. Never
		# raises, so a logging failure never prevents the Call Log update
		# above from being marked Completed.
		upload_conversation_to_s3(
			"outbound",
			payload.get("interaction_id"),
			campaign_id=payload.get("campaign_id"),
			recording_url=payload.get("recording_url"),
			transcript=transcript,
		)

		request_log.status = "Completed"
	except Exception:
		request_log.status = "Failed"
		request_log.error = frappe.get_traceback()
		frappe.db.rollback()
		frappe.log_error(title="Error while updating CRM Call Log from Sarvam webhook")
		frappe.db.commit()
	finally:
		request_log.save(ignore_permissions=True)
		frappe.db.commit()
