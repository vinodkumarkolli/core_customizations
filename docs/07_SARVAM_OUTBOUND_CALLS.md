# Manual 07 — Sarvam AI Outbound Support Calls

**Files**: `sarvam_telephony.py`, `monkey_patches.py`, `doctype/sarvam_outbound_settings/`, `fixtures/property_setter.json`

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

There is currently **no button on the Issue form** — call it directly:

```python
frappe.call({
    method: "core_customizations.core_customizations.sarvam_telephony.trigger_support_call",
    args: { issue_name: "ISS-00123" },
    callback: (r) => console.log("Call Log:", r.message)
})
```

or from the console:

```bash
bench --site <site> execute core_customizations.core_customizations.sarvam_telephony.trigger_support_call --args '["ISS-00123"]'
```

It will:

1. Check the calling user has a `CRM Telephony Agent` record (refuses otherwise).
2. Resolve a phone number from the Issue's linked `Contact`.
3. Create a `CRM Call Log` (`telephony_medium = Sarvam`, `type = Outgoing`, `status = Initiated`, `caller = <you>`, `reference_doctype = Issue`).
4. POST to Sarvam's instant-outbound API with the Issue's context (`issue_subject`, `customer_name`, `ticket_status`) and your mobile number as `transfer_to`.
5. Store Sarvam's `attempt_id` on the Call Log's `id` field, for matching the later webhook.

Adding a "Call via Sarvam" button to the Issue form is a follow-up, not yet built.

---

## The Webhook

Sarvam POSTs the call result to:

```
/api/method/core_customizations.core_customizations.sarvam_telephony.handle_outbound_webhook?key=<webhook_secret>
```

Authenticity is checked via that `key` query param (same workaround CRM's own Exotel handler uses — Sarvam, like Exotel, does not sign its webhook). Every payload is logged via `create_request_log` regardless of outcome, so a shape mismatch is visible in **Integration Request** rather than silently dropped.

The handler updates the Call Log's `status` (mapped from Sarvam's `connectivity_status` + `completion_status`), `duration`, and `recording_url`, and — if present — adds the `interaction_transcript` as a comment on the Call Log, explicitly labeled "AI side only" (see below).

---

## Known Limitations

- **Transcript coverage is unconfirmed.** Sarvam's "call transfer" is documented as a *blind* handoff — the AI agent's own speech pipeline is not confirmed to remain in the audio path after the transfer. `interaction_transcript` may only ever contain the brief greeting, not the actual staff-to-customer conversation. **Place one real test call and check the webhook payload before relying on this for anything beyond basic call logging.**
- **No call-status polling.** Sarvam's instant-outbound endpoint returns only `{"attempt_id": ...}` with no documented GET-by-id status endpoint — the Call Log stays `Initiated` until the webhook arrives. There is no timeout/retry handling for a webhook that never arrives.
- **Leftover tool bindings.** The "Support Outbound" agent was cloned from the Order Desk agent and still lists ~19 inherited Order Desk tool bindings (`global_tool_names`) it has no reason to call. Harmless — the prompt never invokes them — but worth pruning on the Sarvam dashboard for clarity.
- **No UI entry point.** Calling only works via API/console today (see above).

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `PermissionError: You are not registered as a CRM Telephony Agent` | Caller has no `CRM Telephony Agent` record | Create one for them with their `mobile_no` set |
| `Sarvam Outbound Settings is not enabled` | `enabled` unchecked, or doc never filled in | Fill in and enable **Sarvam Outbound Settings** |
| `Sarvam Outbound Settings is missing: ...` | One or more required fields blank | Fill in the named fields |
| `Issue {name} has no contact phone number to call` | Issue's `contact` is blank, or that Contact has no `mobile_no`/`phone` | Set a Contact with a phone number on the Issue |
| Call Log stuck on `Initiated` forever | Webhook never arrived — check `Integration Request` list for "Sarvam Outbound Call" entries, or the URL/secret is wrong | Verify `webhook_secret` matches, and that the site is reachable from the public internet |
| `401`/`Unauthorized request` in Integration Request error | `key` query param doesn't match `webhook_secret` | Re-check `Sarvam Outbound Settings.webhook_secret` |
| Call connects but transfer never happens | Connection isn't Vobiz, or `call_transfer_config`/`transfer_to` got reset on a later agent edit | Re-check the agent's `interaction_config.call_transfer_config` on the Sarvam dashboard |
| Customer hears the wrong greeting ("order desk" etc.) | Agent was recommitted from a fresh clone, losing the Support-specific prompt/intro | Re-apply the Support prompt and intro message, then recommit and bump `support_agent_version` |

---

## Related Business Rules

See [Business Blueprint — Epic 10](../.agents/rules/business_blueprint.md):

- `[BR-TEL-001]` Support Ticket Call Resolution — how an inbound/existing call resolves to an Issue.
- `[BR-TEL-002]` Sarvam Integration Visibility & the outbound trigger/webhook itself.
- `[BR-TEL-003]` Sarvam outbound calling is human-to-human, restricted to registered agents.
