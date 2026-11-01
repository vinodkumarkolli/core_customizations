# Manual 07 — Sarvam AI Outbound Support Calls

**Files**: `sarvam_telephony.py`, `monkey_patches.py`, `doctype/sarvam_outbound_settings/`, `fixtures/property_setter.json`, `fixtures/client_script.json`

---

## Overview

This app lets a registered support agent place an outbound call about an open **Issue** (Support ticket) through **Sarvam AI**, and have it logged as a **CRM Call Log** alongside Twilio/Exotel calls.

**Important — this is a human-to-human call, not an AI conversation.** The Sarvam voice agent does not negotiate with the customer. It:

1. Dials the Issue's contact.
2. Says one or two short sentences confirming it's Sravi Enterprises Support calling about the ticket.
3. Immediately **blind-transfers** the live call to the mobile number of the staff member who triggered it.

From that point on, the staff member and the customer are talking directly — Sarvam's only remaining job is to have bridged the call and, if the AI agent's own speech recognition is still in the audio path, to turn the resulting audio into a transcript. See [Known Limitations](#known-limitations) for why that last part isn't guaranteed.

```
Frappe (trigger_support_call)
   │  POST /outbounds  (fire-and-forget)
   ▼
Sarvam platform ── dials customer ──► "Hi, this is Sravi Enterprises Support
                                        calling about ticket ...  Connecting
                                        you now."
                                        │
                                        ▼ blind call_transfer
                                   Staff member's own mobile rings
                                        │
                                        ▼
                         Customer <──────────► Staff member (live call)
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
| Committed agent version | `3` | Bumped every time the agent's prompt/config is recommitted |
| Org ID | `01a163ae-efc7-75ff-8021-ba55a92f10b1` | Sarvam dashboard |
| Workspace ID | `01a163ae-efd3-770f-b264-6bc423b9c34b` | Sarvam dashboard |

**Note:** this feature talks to Sarvam's own hosted outbound-agent REST API directly. It does **not** use the `voice-agents` skill at `.agents/skills/sarvam-skills/voice-agents` (that skill covers self-hosting a LiveKit/Pipecat agent) — the agent here runs entirely on Sarvam's platform.

Transfer only works on **Vobiz** telephony connections — if the connection is ever swapped for a different provider, the call-transfer step will stop working even if everything else is configured correctly.

---

## Setup Steps

### 1. Register staff as CRM Telephony Agents

Outbound calling is restricted to users who already have a **CRM Telephony Agent** record ([BR-TEL-003](../.agents/rules/business_blueprint.md)) — the same record CRM's own Twilio/Exotel calling uses. That record's `mobile_no` is also where the call gets transferred to.

1. Go to **CRM Telephony Agent** (list).
2. Create one record per staff member who should be able to place Support outbound calls.
3. Set `user` to their Frappe user, and `mobile_no` to their own mobile number (E.164, e.g. `+919876543210`).

A user with no record here is refused with a clear error, not silently skipped.

### 2. Configure Sarvam Outbound Settings

Go to **Sarvam Outbound Settings** (Single DocType) and fill in:

| Field | Value |
|---|---|
| `enabled` | ✅ |
| `org_id` | `01a163ae-efc7-75ff-8021-ba55a92f10b1` |
| `workspace_id` | `01a163ae-efd3-770f-b264-6bc423b9c34b` |
| `support_agent_id` | `Support-Out-2128e33d-0fd3` |
| `support_agent_version` | `3` (the current committed version — bump this if the agent is recommitted) |
| `support_connection_id` | `8cbb7cc8-d8-abd294c3-1f9b` |
| `support_agent_phone_number` | `+918064276261` |
| `outbound_api_key` | Your Sarvam workspace API key (`X-API-Key` header — **not** the `api-subscription-key` used by Sarvam's STT/TTS/LLM SDKs, that's a different API surface) |
| `webhook_secret` | Any secret you choose — used to authenticate Sarvam's call-end webhook back to this site |

All fields are `Password` type where they hold a secret, so they're encrypted at rest and never shown back in the UI.

### 3. Verify `telephony_medium` accepts "Sarvam"

A Property Setter fixture already adds `Sarvam` to `CRM Call Log.telephony_medium`'s options. If you don't see it after a fresh install, run:

```bash
bench --site <site> migrate
```

---

## Triggering a Call

A **"Call via Sarvam"** button appears in the Issue form's **Actions** menu (added via the `Issue Sarvam Call Script` Client Script fixture). It just calls `trigger_support_call(issue_name)` and shows a toast — all the real logic is server-side.

You can also call it directly from the console:

```bash
bench --site <site> execute core_customizations.core_customizations.sarvam_telephony.trigger_support_call --args '["ISS-00123"]'
```

It will:

1. Check the calling user has a `CRM Telephony Agent` record (refuses otherwise).
2. Resolve a phone number from the Issue's linked `Contact`.
3. Create a `CRM Call Log` (`telephony_medium = Sarvam`, `type = Outgoing`, `status = Initiated`, `caller = <you>`, `from = <Sarvam caller ID>`, `to = <customer number>`, `reference_doctype = Issue`).
4. POST to Sarvam's instant-outbound API with the Issue's context (`issue_subject`, `customer_name`, `ticket_status`) and your mobile number as `transfer_to`.
5. Store Sarvam's `attempt_id` on the Call Log's `id` field if the response includes one (best-effort — not always populated; the webhook's `webhook_config.metadata.call_log` is the reliable match, see below).

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

`trigger_support_call` uses this site-config key in preference to `frappe.utils.get_url()` when present. Unset it (or leave it unset in production, where the real domain is reachable) once you're done — a stale tunnel URL here means every subsequent call's webhook silently goes nowhere.

---

## Known Limitations

- **Webhook payload shape is only partially confirmed.** One real delivery (status `"busy"`) confirmed the overall shape and that `status` is flat, not `connectivity_status`/`completion_status`. The sibling status values (`completed`, `no_answer`, `failed`, etc.) and whether `interaction_transcript` is ever populated for a *connected and transferred* call are still unconfirmed — a call that was busy obviously never got far enough to produce one. **Place a test call that actually connects and transfers, and check the resulting webhook payload, before relying on transcript or status values beyond "busy".**
- **No call-status polling.** Sarvam's instant-outbound endpoint returns only `{"attempt_id": ...}` with no documented GET-by-id status endpoint — the Call Log stays `Initiated` until the webhook arrives. There is no timeout/retry handling for a webhook that never arrives.
- **`attempt_id` capture on the Call Log is unreliable.** `trigger_support_call` stores it on the Call Log's `id` field only if Sarvam's synchronous POST response includes it — observed inconsistently across test calls (present on one, absent on another, cause not yet root-caused). Harmless in practice since the webhook matches via `webhook_config.metadata.call_log` instead, which is reliable — but don't depend on the Call Log's `id` field alone to find a Sarvam attempt.
- **Leftover tool bindings.** The "Support Outbound" agent was cloned from the Order Desk agent and still lists ~19 inherited Order Desk tool bindings (`global_tool_names`) it has no reason to call. Harmless — the prompt never invokes them — but worth pruning on the Sarvam dashboard for clarity.
- **A "busy" result can come from either leg.** The payload's `channel_info` names the Sarvam-side number, not which leg (customer or transfer target) reported busy. If a call keeps coming back `"busy"`, check both the Issue's contact number and the triggering user's own `CRM Telephony Agent.mobile_no` — it could be either one.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `PermissionError: You are not registered as a CRM Telephony Agent` | Caller has no `CRM Telephony Agent` record | Create one for them with their `mobile_no` set |
| `Sarvam Outbound Settings is not enabled` | `enabled` unchecked, or doc never filled in | Fill in and enable **Sarvam Outbound Settings** |
| `Sarvam Outbound Settings is missing: ...` | One or more required fields blank | Fill in the named fields |
| `Issue {name} has no contact phone number to call` | Issue's `contact` is blank, or that Contact has no `mobile_no`/`phone` | Set a Contact with a phone number on the Issue |
| Call Log stuck on `Initiated` forever, no `Integration Request` for "Sarvam Outbound Call" at all | Webhook never reached this site — almost certainly `development.localhost` (or similar) isn't publicly reachable | Set up a tunnel and `sarvam_webhook_base_url`, see [Testing the webhook locally](#testing-the-webhook-locally) |
| `401`/`Unauthorized request` in Integration Request error | `key` query param doesn't match `webhook_secret` | Re-check `Sarvam Outbound Settings.webhook_secret` |
| Call Log shows `Completed` for a call you know failed/was busy | Running code predates the `SARVAM_STATUS_MAP` fix — the old handler read `connectivity_status`/`completion_status`, fields that don't exist on this endpoint's real payload, and silently defaulted to `"Completed"` | Make sure `sarvam_telephony.py` has `_map_sarvam_call_status(status)` reading the flat `status` field, not the two-field version |
| Phone rings very briefly then disconnects, Call Log ends up `Busy` | Sarvam/Vobiz got a busy signal on one of the two legs — check `channel_info` in the logged payload; it doesn't say which leg | Confirm both numbers are reachable and not already on another call: the Issue's contact, and the triggering user's `CRM Telephony Agent.mobile_no` |
| Call connects but transfer never happens | Connection isn't Vobiz, or `call_transfer_config`/`transfer_to` got reset on a later agent edit | Re-check the agent's `interaction_config.call_transfer_config` on the Sarvam dashboard |
| Customer hears the wrong greeting ("order desk" etc.) | Agent was recommitted from a fresh clone, losing the Support-specific prompt/intro | Re-apply the Support prompt and intro message, then recommit and bump `support_agent_version` |

---

## Related Business Rules

See [Business Blueprint — Epic 10](../.agents/rules/business_blueprint.md):

- `[BR-TEL-001]` Support Ticket Call Resolution — how an inbound/existing call resolves to an Issue.
- `[BR-TEL-002]` Sarvam Integration Visibility & the outbound trigger/webhook itself.
- `[BR-TEL-003]` Sarvam outbound calling is human-to-human, restricted to registered agents.
