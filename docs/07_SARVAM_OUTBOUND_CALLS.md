# Manual 07 — Sarvam AI Outbound Calls

**Files**: `sarvam_telephony.py`, `monkey_patches.py`, `doctype/sarvam_voice_agent_settings/`, `fixtures/property_setter.json`, `fixtures/client_script.json`, `pyproject.toml` (boto3)

---

## Overview

This app lets a registered agent place an outbound call about an **Issue** (Support ticket), **CRM Lead**, or **CRM Deal** through **Sarvam AI**, and have it logged as a **CRM Call Log** alongside Twilio/Exotel calls. It's one generic mechanism (`trigger_sarvam_call(reference_doctype, reference_name)`) — adding another doctype means registering a resolver, not building a new feature; see `SARVAM_CALL_CONTEXT_RESOLVERS` in `sarvam_telephony.py`.

**Important — this is a human-to-human call, not an AI conversation.** The Sarvam voice agent never speaks to the customer at all. It:

1. Dials the **resolved telephony agent's own mobile first** (their `CRM Telephony Agent.mobile_no`) — the triggering user's own by default, or a different registered agent if picked via the "Call As" dialog field.
2. Immediately states who they're being connected to (contact name and number), then asks them to read back a **4-digit verification code** — generated per call and shown to the user who clicked "Call via Sarvam" in a popup — one digit at a time, and only continues on a match (up to two retries).
3. Once verified, briefly mentions what the call is about (record type, subject, status).
4. Immediately **blind-transfers** the live call to the customer.

The intro that plays the instant the staff member picks up is a short, fixed line ("Hello, this is Sravi Enterprises.") — it cannot carry per-call details like the contact name or phone number, since it's pre-rendered audio set once on the agent, not generated per call. All of the call-specific content (who you're being connected to, the OTP ask, the record brief) comes from the prompt-driven turn that follows it, not the intro itself.

This ordering is deliberate: the customer's phone only starts ringing once the staff member is already live on the line, so when they pick up they're speaking directly to a human with no AI greeting or dead air on their end. (An earlier version of this flow dialed the customer first — worse, since the customer would hear the AI, then wait while the staff member's phone rang.) The verification code exists so both the person who triggered the call and the person who answers it confirm they're talking about the same intended call — not voicemail, and not a stranger who happened to pick up the staff member's phone.

```
Frappe (trigger_sarvam_call)
   │  generates a 4-digit code, returns it to the browser popup
   │  POST /outbounds  (fire-and-forget)
   ▼
Sarvam platform ── dials staff member ──► "Hello, this is Sravi
                                            Enterprises." (fixed intro)
                                            │
                                            ▼
                                       "Connecting you to <customer>
                                        at <number>. Please read the
                                        code on your screen, one digit
                                        at a time." ── staff reads it ──►
                                            match? ── no ──► retry (up to 2x), then end
                                            │ yes
                                            ▼
                                       "This is about <record> for
                                        <customer>, status ..."
                                            │
                                            ▼ blind call_transfer
                                       Customer's own mobile rings
                                            │
                                            ▼
                         Staff member <──────────► Customer (live call)
                                            │
                                            ▼ (call ends)
Frappe (handle_outbound_webhook) ◄── webhook POST ── Sarvam platform
   │
   ▼
CRM Call Log updated (status, duration, recording, transcript comment)
```

---

## Prerequisites

This feature was built against one Sarvam workspace with:

| Item | Current value | Where it comes from |
|---|---|---|
| Telephony connection | `8cbb7cc8-d8-abd294c3-1f9b` (provider: vobiz) | Sarvam dashboard → Telephony |
| Onboarded number | `+918064276261` | Same connection |
| Voice agent | `Support-Out-2128e33d-0fd3` ("Support Outbound") | Cloned from the existing Order Desk agent |
| Committed agent version | `9` | Bumped every time the agent's prompt/config is recommitted — **update `Sarvam Voice Agent Settings.support_agent_version` to match whenever this changes** |
| Org ID | `01a163ae-efc7-75ff-8021-ba55a92f10b1` | Sarvam dashboard |
| Workspace ID | `01a163ae-efd3-770f-b264-6bc423b9c34b` | Sarvam dashboard |

**Note:** this feature talks to Sarvam's own hosted outbound-agent REST API directly. It does **not** use the `voice-agents` skill at `.agents/skills/sarvam-skills/voice-agents` (that skill covers self-hosting a LiveKit/Pipecat agent) — the agent here runs entirely on Sarvam's platform.

Transfer only works on **Vobiz** telephony connections — if the connection is ever swapped for a different provider, the call-transfer step will stop working even if everything else is configured correctly.

---

## Setup Steps

### 1. Register staff as CRM Telephony Agents

Outbound calling is restricted to users who already have a **CRM Telephony Agent** record ([BR-TEL-003](../.agents/rules/business_blueprint.md)) — the same record CRM's own Twilio/Exotel calling uses. That record's `mobile_no` is also where the call gets transferred to.

1. Go to **CRM Telephony Agent** (list).
2. Create one record per staff member who should be able to place Sarvam outbound calls.
3. Set `user` to their Frappe user, and `mobile_no` to their own mobile number (E.164, e.g. `+919876543210`).

A user with no record here is refused with a clear error, not silently skipped.

### 2. Configure Sarvam Voice Agent Settings

Go to **Sarvam Voice Agent Settings** (Single DocType — renamed from "Sarvam Outbound Settings" on 2026-11-02; the existing fields now live under its **"Sarvam Outbound Settings"** section, alongside a new **"Call Logging Settings"** section, see below) and fill in the Outbound Settings section:

| Field | Value |
|---|---|
| `enabled` | ✅ |
| `org_id` | `01a163ae-efc7-75ff-8021-ba55a92f10b1` |
| `workspace_id` | `01a163ae-efd3-770f-b264-6bc423b9c34b` |
| `support_agent_id` | `Support-Out-2128e33d-0fd3` |
| `support_agent_version` | `9` (the current committed version — bump this if the agent is recommitted) |
| `support_connection_id` | `8cbb7cc8-d8-abd294c3-1f9b` |
| `support_agent_phone_number` | `+918064276261` |
| `outbound_api_key` | Your Sarvam workspace API key (`X-API-Key` header — **not** the `api-subscription-key` used by Sarvam's STT/TTS/LLM SDKs, that's a different API surface) |
| `webhook_secret` | Any secret you choose — used to authenticate Sarvam's call-end webhook back to this site |

All fields are `Password` type where they hold a secret, so they're encrypted at rest and never shown back in the UI.

### 2a. (Optional) Configure Call Logging Settings

A separate section on the same doctype, gated by its own `enable_call_logging` checkbox — independent of outbound calling, since this is meant to eventually cover inbound calls too (see Known Limitations). When enabled, every outbound call's recording and transcript are uploaded to S3, keyed by Sarvam's `interaction_id`, via `upload_conversation_to_s3()` in `sarvam_telephony.py`.

| Field | Value |
|---|---|
| `enable_call_logging` | ✅ |
| `s3_bucket` | Your S3 bucket name |
| `s3_region` | e.g. `ap-south-1` |
| `s3_access_key_id` / `s3_secret_access_key` | IAM credentials with `s3:PutObject` on the bucket |
| `s3_endpoint_url` | Leave blank for AWS S3; set this for an S3-compatible store (MinIO, R2, ...) |
| `s3_inbound_path_prefix` | Default `inbound` |
| `s3_outbound_path_prefix` | Default `outbound` |

**Layout:**

```
<s3_outbound_path_prefix>/<interaction_id>.mp3        # a single outbound call
<s3_outbound_path_prefix>/<interaction_id>.json        # its transcript
<s3_outbound_path_prefix>/<campaign_id>/<interaction_id>.mp3   # outbound call placed via a Sarvam campaign
<s3_inbound_path_prefix>/<interaction_id>.mp3          # an inbound call
```

Calls placed as part of a Sarvam **campaign** (bulk/cohort dialing — not used by this app's current instant-outbound flow, which only ever places single calls) are nested one level deeper under `campaign_id`, so a campaign's recordings can be browsed as one group. A call with no `campaign_id` sits flat under the prefix.

The upload never raises: a failure here (bad credentials, bucket typo, network issue) is logged via `frappe.log_error` but never breaks the webhook's primary job of updating the CRM Call Log.

### 3. Verify `telephony_medium` accepts "Sarvam"

A Property Setter fixture already adds `Sarvam` to `CRM Call Log.telephony_medium`'s options. If you don't see it after a fresh install, run:

```bash
bench --site <site> migrate
```

---

## Triggering a Call

A **"Call via Sarvam"** button appears in the **Actions** menu on:

- The Issue form (classic Desk view) — `Issue Sarvam Call Script`.
- The CRM Lead form (classic Desk view, `/app/crm-lead/...` or `/desk/fcrm/crm-lead/...` — **not** CRM's own Vue frontend at `/crm/leads/...`, which has its own separate "Make a Call" dialog hardcoded to Twilio/Exotel and isn't touched by this) — `CRM Lead Sarvam Call Script`.

Both open a small dialog first — a **"Call As"** `Link` field to `CRM Telephony Agent`, left blank by default — then call `trigger_sarvam_call(reference_doctype, reference_name, telephony_agent)` and, on success, show a popup with the **verification code** the resolved agent will be asked to read back. There is no button on CRM Deal yet, though the server-side resolver already supports it (see below).

**Call As**: leave it blank to take the call yourself (the default — same behavior as before this field existed). Pick a different registered `CRM Telephony Agent` to route the call to them instead — e.g. a dispatcher placing the call for whichever teammate is actually free. Triggering the call at all still requires *you* to be a registered `CRM Telephony Agent` ([BR-TEL-003]) — picking someone else only changes who gets dialed, not who may use this button.

You can also call it directly from the console:

```bash
bench --site <site> execute core_customizations.core_customizations.sarvam_telephony.trigger_sarvam_call --args '["Issue", "ISS-00123"]'
bench --site <site> execute core_customizations.core_customizations.sarvam_telephony.trigger_sarvam_call --args '["CRM Lead", "CRM-LEAD-2026-00001"]'
bench --site <site> execute core_customizations.core_customizations.sarvam_telephony.trigger_sarvam_call --args '["CRM Lead", "CRM-LEAD-2026-00001"]' --kwargs "{'telephony_agent': 'teammate@example.com'}"
```

It will:

1. Check `reference_doctype` is supported (`Issue`, `CRM Lead`, `CRM Deal` — see `SARVAM_CALL_CONTEXT_RESOLVERS`), and the calling user has a `CRM Telephony Agent` record (refuses otherwise — this check is unaffected by `telephony_agent`).
2. Resolve which `CRM Telephony Agent` actually gets dialed (`_resolve_telephony_agent`) — `telephony_agent` if given (its `name` is the target user's id, since the doctype is autonamed `field:user`), else the calling user's own record. Refuses if that agent doesn't exist or has no `mobile_no`.
3. Resolve a phone number and context (subject, contact name, status) from the record — an Issue's linked `Contact`, a CRM Lead's own `mobile_no`/`phone`, or a CRM Deal's primary `CRM Contacts` row.
4. Generate a random 4-digit **verification code** (`_generate_verification_code`).
5. Create a `CRM Call Log` (`telephony_medium = Sarvam`, `type = Outgoing`, `status = Initiated`, `caller = <resolved agent's user>`, `from = <Sarvam caller ID>`, `to = <customer number>`, `reference_doctype = <Issue/CRM Lead/CRM Deal>`).
6. POST to Sarvam's instant-outbound API with the resolved agent's mobile as `user_phone_number` (the number Sarvam dials first), the verification code and the record's context (`record_doctype_label`, `record_name`, `record_subject`, `contact_name`, `record_status`) as agent variables, plus the customer's number as `transfer_to` (where Sarvam blind-transfers once the agent is verified and briefed).
7. Store Sarvam's `attempt_id` on the Call Log's `id` field if the response includes one (best-effort — not always populated; the webhook's `webhook_config.metadata.call_log` is the reliable match, see below).
8. Return `{"call_log": <name>, "verification_code": <code>}` — the Client Scripts use the latter to show the popup; the code is **not** persisted anywhere (not on the Call Log, not logged) once the response is sent.

---

## The Webhook

Sarvam POSTs the call result to:

```
/api/method/core_customizations.core_customizations.sarvam_telephony.handle_outbound_webhook?key=<webhook_secret>
```

Authenticity is checked via that `key` query param (same workaround CRM's own Exotel handler uses — Sarvam, like Exotel, does not sign its webhook). Every payload is logged via `create_request_log` regardless of outcome, so a shape mismatch is visible in **Integration Request** rather than silently dropped.

**The real payload shape** (confirmed 2026-11-02 against a live test call — it does **not** match Sarvam's documented campaign-webhook schema at `sarvam://schemas/webhook-payload`, which describes a different endpoint):

```json
{
  "app_id": "Support-Out-2128e33d-0fd3", "app_version": 3,
  "attempt_id": "1a830d1e-3cd2-401c-95ef-b3695517945d",
  "channel_info": {"agent_phone_number": "+918064276261", "channel_provider": "vobiz", "channel_type": "v2v"},
  "duration": null, "end_datetime": null, "failure_reason": null,
  "final_agent_variables": null, "interaction_id": null,
  "interaction_transcript": null, "output_agent_variables": null,
  "recording_url": null, "start_datetime": null,
  "status": "busy",
  "webhook_config": {"metadata": {"call_log": "..."}, "url": "..."}
}
```

Key differences from the documented schema: a single flat `status` field (not `connectivity_status` + `completion_status`), no `campaign_id`/`cohort_id`, and — important — **`metadata` is nested under the echoed `webhook_config`, not at the top level**. The handler checks `webhook_config.metadata` first, falling back to a top-level `metadata` and then `attempt_id` matching, to stay robust if the shape shifts again.

The handler maps `status` onto the Call Log's own `status` field via `SARVAM_STATUS_MAP` in `sarvam_telephony.py` — only `"busy"` is confirmed from a real delivery so far; the rest of the map is a best-effort guess at the sibling values, and anything unrecognised defaults to `"Failed"` (logged to Error Log) rather than being silently reported as `"Completed"`. It also sets `duration`/`recording_url` when present, and — if `interaction_transcript` is non-empty — adds it as a comment on the Call Log, explicitly labeled "AI side only" (see below).

### Testing the webhook locally

`development.localhost` (or any non-public dev site) is not reachable from Sarvam's servers, so the webhook will never arrive without a public tunnel. Run one (e.g. `cloudflared tunnel --url http://localhost:8000`), then point the webhook at it **without** changing the site's global `host_name`:

```bash
bench --site <site> set-config sarvam_webhook_base_url "https://<your-tunnel-subdomain>.trycloudflare.com"
```

`trigger_sarvam_call` uses this site-config key in preference to `frappe.utils.get_url()` when present. Unset it (or leave it unset in production, where the real domain is reachable) once you're done — a stale tunnel URL here means every subsequent call's webhook silently goes nowhere.

---

## Known Limitations

- **Webhook payload shape is only partially confirmed.** One real delivery (status `"busy"`) confirmed the overall shape and that `status` is flat, not `connectivity_status`/`completion_status`. The sibling status values (`completed`, `no_answer`, `failed`, etc.) and whether `interaction_transcript` is ever populated for a *connected and transferred* call are still unconfirmed — a call that was busy obviously never got far enough to produce one. **Place a test call that actually connects and transfers, and check the resulting webhook payload, before relying on transcript or status values beyond "busy".**
- **No call-status polling.** Sarvam's instant-outbound endpoint returns only `{"attempt_id": ...}` with no documented GET-by-id status endpoint — the Call Log stays `Initiated` until the webhook arrives. There is no timeout/retry handling for a webhook that never arrives.
- **`attempt_id` capture on the Call Log is unreliable.** `trigger_sarvam_call` stores it on the Call Log's `id` field only if Sarvam's synchronous POST response includes it — observed inconsistently across test calls (present on one, absent on another, cause not yet root-caused). Harmless in practice since the webhook matches via `webhook_config.metadata.call_log` instead, which is reliable — but don't depend on the Call Log's `id` field alone to find a Sarvam attempt.
- **A "busy" result can come from either leg.** The payload's `channel_info` names the Sarvam-side number, not which leg (customer or triggering staff member) reported busy. If a call keeps coming back `"busy"`, check both the record's contact number and the triggering user's own `CRM Telephony Agent.mobile_no` — it could be either one.
- **No button on CRM Deal yet.** The resolver (`_get_crm_deal_call_context`) exists and is wired into `trigger_sarvam_call`, but no Client Script adds the button there — only console/API access for now.
- **Inbound webhook payload shape is unconfirmed.** `handle_inbound_webhook` (added 2026-11-02, see [BR-TEL-005](../.agents/rules/business_blueprint.md)) parses the `InboundWebhookPayload` shape documented at `sarvam://schemas/webhook-payload` (`app_id`, `app_version`, `deployment_id`, `interaction_id`, `user_phone_number`, `agent_phone_number`, `duration`, `recording_url`, `start_datetime`, `end_datetime`, `final_agent_variables`, `output_agent_variables`, `interaction_transcript`, `metadata`) — but unlike the outbound endpoint, this has **not** been checked against a real delivery yet, and the outbound endpoint's own documented schema was already confirmed wrong once (see above). Every payload is still logged via `create_request_log` regardless, so a shape mismatch is visible rather than silently dropped. Point the inbound deployment's webhook config (set via Sarvam's `telephony` tooling, not from this app) at:
  ```
  /api/method/core_customizations.core_customizations.sarvam_telephony.handle_inbound_webhook?key=<webhook_secret>
  ```
  and place a real test call before relying on it.
- **Campaign sub-foldering (`<outbound_prefix>/<campaign_id>/...`) is untested.** This app's `trigger_sarvam_call` only ever uses Sarvam's instant-outbound (single-call) API, which never returns a `campaign_id` — the sub-foldering logic in `_build_s3_key` is forward-looking for whenever campaign-based bulk outbound dialing is added, and has not been exercised against a real campaign webhook payload.
- **Ring duration on the staff leg is not configurable from here.** Checked the full agent-config schema, the Vobiz connection, and the outbound REST payload — none expose a ring/dial-timeout setting; it's controlled by Sarvam's telephony infrastructure itself. If the staff member's phone isn't ringing long enough to answer, that needs to go to Sarvam support directly.
- **Verification-code mismatch handling is prompt-driven, not deterministic — and DTMF keypad entry is not available on this platform.** The agent compares the staff member's spoken digits to `{{verification_code}}` via the LLM/STT pipeline. **Confirmed by a real test call (2026-11-02, app_version 7):** the payload correctly carried `verification_code: "6880"` (seen in the webhook's `final_agent_variables`), but STT transcribed the staff member reading it aloud as "It's complete zero" and then "880" — both misreads of a correctly-spoken code, and the call was ended after exhausting the single retry. Checked whether the staff member could instead key the code in on their keypad (e.g. `*6880#`) to sidestep STT entirely: the only DTMF-related field anywhere in the agent-config schema or this workspace's four tool kinds (API, Integration/MCP, Data Validator, Data Verifier) is `call_transfer_config.post_dial_digits` — digits the *agent sends* on transfer, not digits it *listens for* from the caller. There is no keypad-capture capability exposed here, so this stays voice-only. The accepted mitigation (as of v9): ask the staff member to read the code **one digit at a time** with pauses, and allow **two retries** (three attempts total) to tolerate STT noise. Not yet re-tested against a real call.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `PermissionError: You are not registered as a CRM Telephony Agent` | Caller has no `CRM Telephony Agent` record | Create one for them with their `mobile_no` set |
| `Sarvam outbound calling is not enabled` | `enabled` unchecked, or doc never filled in | Fill in and enable the Outbound Settings section of **Sarvam Voice Agent Settings** |
| `Sarvam Voice Agent Settings is missing: ...` | One or more required fields blank | Fill in the named fields |
| `Sarvam call logging is not enabled` | `enable_call_logging` unchecked, or doc never filled in | Fill in and enable the Call Logging Settings section of **Sarvam Voice Agent Settings** |
| `Sarvam calling does not support {doctype}` | `reference_doctype` isn't registered in `SARVAM_CALL_CONTEXT_RESOLVERS` | Only `Issue`, `CRM Lead`, `CRM Deal` are supported; add a resolver for anything else |
| `{doctype} {name} has no contact phone number to call` | Issue's `contact` is blank (or that Contact has no `mobile_no`/`phone`), or the CRM Lead/Deal itself has no number on it | Set a phone number on the record (or its Contact, for Issue/Deal) |
| Call Log stuck on `Initiated` forever, no `Integration Request` for "Sarvam Outbound Call" at all | Webhook never reached this site — almost certainly `development.localhost` (or similar) isn't publicly reachable | Set up a tunnel and `sarvam_webhook_base_url`, see [Testing the webhook locally](#testing-the-webhook-locally) |
| `401`/`Unauthorized request` in Integration Request error | `key` query param doesn't match `webhook_secret` | Re-check `Sarvam Voice Agent Settings.webhook_secret` |
| No recording/transcript appears in S3, no error shown to the user | `upload_conversation_to_s3` swallows every failure (by design, so it never breaks the Call Log update) | Check **Error Log** for "Sarvam call-logging S3 upload failed"; verify bucket name, region, and credentials |
| Call Log shows `Completed` for a call you know failed/was busy | Running code predates the `SARVAM_STATUS_MAP` fix — the old handler read `connectivity_status`/`completion_status`, fields that don't exist on this endpoint's real payload, and silently defaulted to `"Completed"` | Make sure `sarvam_telephony.py` has `_map_sarvam_call_status(status)` reading the flat `status` field, not the two-field version |
| Phone rings very briefly then disconnects, Call Log ends up `Busy` | Sarvam/Vobiz got a busy signal on one of the two legs — check `channel_info` in the logged payload; it doesn't say which leg | Confirm both numbers are reachable and not already on another call: the record's contact, and the triggering user's `CRM Telephony Agent.mobile_no` |
| Call connects but transfer never happens | Connection isn't Vobiz, or `call_transfer_config`/`transfer_to` got reset on a later agent edit | Re-check the agent's `interaction_config.call_transfer_config` on the Sarvam dashboard |
| Staff member hears the wrong greeting ("order desk" etc.), or the customer's phone rings before the staff member's | Agent was recommitted from a fresh clone, losing the Sarvam-calling prompt/intro, or `user_config.user_phone_number`/`transfer_to` got swapped back | Re-apply the prompt and intro message, recommit and bump `support_agent_version`; confirm `trigger_sarvam_call` sends `caller_mobile` as `user_phone_number` and the customer's number as `transfer_to` |
| Agent ends the call saying the code didn't match, even though the staff member read it correctly | STT misheard the spoken digits, or they read the stale code from a previous popup | Check the exact code in the popup shown at trigger time (it's never persisted, so there's nothing to look up after the fact); retry the call |

---

## Related Business Rules

See [Business Blueprint — Epic 10](../.agents/rules/business_blueprint.md):

- `[BR-TEL-001]` Support Ticket Call Resolution — how an inbound/existing call resolves to an Issue.
- `[BR-TEL-002]` Sarvam Integration Visibility & the outbound trigger/webhook itself.
- `[BR-TEL-003]` Sarvam outbound calling is human-to-human, restricted to registered agents.
- `[BR-TEL-004]` Call recording/transcript archival to S3.
- `[BR-TEL-005]` Inbound call logging — how `handle_inbound_webhook` creates the Call Log and resolves the caller.
