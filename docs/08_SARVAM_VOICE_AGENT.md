# Manual 08 — Sarvam Inbound Voice Agent: Server Methods

**Files**: `voice_agent.py`, `sarvam_telephony.py` (`handle_inbound_webhook`), `doctype/sarvam_voice_agent_settings/`, `doctype/sarvam_transfer_executive/`, `doctype/sarvam_caller_category/`, `doctype/sarvam_pack_item/`, `patches/v1_0/seed_sarvam_voice_agent_rules.py`, `tests/test_voice_agent.py`
**Rules**: `[BR-TEL-006]`, `[BR-TEL-007]`, `[BR-CRM-004]`–`[BR-CRM-007]` (see `.agents/rules/business_blueprint.md`)
**Sample responses**: [`docs/samples/voice_agent_samples.json`](samples/voice_agent_samples.json) — every case below, generated from real calls on the dev site (the record names in it come from a rolled-back session).

---

## Why

The "Sravi Enterprises Customer Care" agent used to run ~16 start/end-of-call tools plus ~16 generic ERPNext tools and orchestrate CRM work itself. That caused repeated lookups, arithmetic mistakes (it quoted 47.62 × 10 = 476.20 for a pack whose price is 476.25, and 48 shipping where the rule charges 60) and half-finished multi-step saves. Each job is now **one call**; the agent only reads back what the server returns.

## Endpoints

All are `POST /api/method/core_customizations.core_customizations.voice_agent.<method>`, `allow_guest` and authenticated by `key` = `Sarvam Voice Agent Settings.webhook_secret` (same as `caller_gate.check`). Responses use the standard `{"message": {...}}` envelope.

Every method first runs `caller_gate.evaluate(phone)`. A blocked or foreign caller gets only:

```json
{"message": {"allowed": false, "reason": "BLOCKED_LIST", "message": "This caller is on the blocked list."}}
```

— no data, no writes. Numbers match on their last 10 digits, so `98411 02004`, `+91 98411-02004`, `919841102004` and `09841102004` are the same caller.

| Method | Replaces | Inputs |
|---|---|---|
| `call_started` (webhook) | `check_blocked`, `lookup_caller_lead`, `lookup_caller_contact`, `lookup_lead_organization`, `lookup_contact_customer`, `fetch_caller_preferences`, `fetch_user_metadata`, `create_call_log` | Sarvam's call-start payload: `user_phone_number`, `interaction_id`, `agent_phone_number`; `key` in the query string |
| `caller_context` | same as above, as a tool instead of a webhook | `phone`, `key`, `call_id` (optional — Sarvam's `interaction_id`) |
| `get_caller_preferences` / `set_caller_preferences` | `fetch_caller_preferences` | `phone`, `key`; set also takes `preferences` (JSON object) and `merge` (default 1) |
| `upsert_quote` | the agent's own price/tax/shipping arithmetic | `phone`, `key`, `items` = `[{"item_code", "qty"}]`, `ship_to_pincode` (optional) |
| `save_request` | the chain of create-lead / create-deal / create-quotation / create-task calls | `phone`, `key`, `name`, `caller_type`, `store_type`, `area`, `organization`, `items`, `address`, `whatsapp_number`, `notes`, `ship_to_pincode` |
| `transfer_target` | `check_transfer_hours` (timeapi.io), `route_to_*` (httpbin) | `phone`, `key` |
| call-ended webhook (`sarvam_telephony.handle_inbound_webhook`, unchanged URL) | `update_call_log`, `update_call_log_conversation_ref` | Sarvam's call-end payload; reads `output_agent_variables.summary`, `.conversation_ref`, `.preferences` |

### Sarvam configuration

- **Call started** webhook: `<site>/api/method/core_customizations.core_customizations.voice_agent.call_started?key=<webhook_secret>`
- **Call ended** webhook: `<site>/api/method/core_customizations.core_customizations.sarvam_telephony.handle_inbound_webhook?key=<webhook_secret>` (as before)

Both payload shapes are still unconfirmed against a real delivery — every delivery is logged as an Integration Request ("Sarvam Call Started" / "Sarvam Inbound Call"), so check the first real ones and adjust the key names at the top of `voice_agent.py` (`CALLER_PHONE_KEYS`, `CALL_ID_KEYS`, `SUMMARY_KEYS`, `CONVERSATION_REF_KEYS`) if Sarvam names them differently.

## Outcomes the agent must handle

**`upsert_quote`** → `status: "quoted"` with `net_total`, `taxes: [{type: CGST|SGST|IGST, rate, amount}]`, `shipping`, `rounding_adjustment`, `grand_total`, `rounded_total`, **`total_to_say`** (read this one aloud), or `status: "error"` with `error`:

| `error` | Meaning / what the agent says |
|---|---|
| `NOT_ON_RECORD` | Caller has no Lead/Customer yet — call `save_request` first (it quotes the same items) |
| `QUOTE_NOT_AVAILABLE` | Category isn't quoted by the agent (wholesale, distributor, retailer) — team calls back |
| `PACK_NOT_AVAILABLE` | Packs of 4/10/20 are for Individual customers only |
| `PINCODE_REQUIRED` | Ask for the delivery pincode, call again with `ship_to_pincode` |
| `PRICE_NOT_FOUND` / `ITEM_NOT_AVAILABLE` / `MIXED_SHIPPING` / `INVALID_ITEMS` | Can't quote these items — team calls back |

**`save_request`** → `status`:

| `status` | Meaning |
|---|---|
| `saved` | New Lead created (+ callback Task; + Deal and draft Quotation when quotable items were given), or an existing Customer's Deal/Quotation |
| `duplicate` | The caller already has a Lead — **no new Lead was created**; `lead` is the existing one, `message` is the `DUPLICATE_LEAD:` token, and the request was recorded on a callback Task against it |
| `blocked` | Caller is blocked/foreign (or became so mid-call — the `CALLER_BLOCKED:` guard fired); nothing saved |
| `error` | `NAME_REQUIRED`, `PHONE_REQUIRED` or `INVALID_ITEMS` — ask and retry |

`warnings` may carry `CUSTOMER_GROUP_NEEDS_REVIEW: retailer` or `UNKNOWN_CATEGORY: <value>` — informational, also written on the Task for the team.

**`transfer_target`** → `open: true` with `target` (then `then[]` in order), or `open: false`, `decision: "CALLBACK"`, `reason` `OUTSIDE_HOURS` / `NOT_ON_RECORD` / `NO_EXECUTIVES`.

## Changes to the agent's required inputs

1. **`caller_type` values** are `individual`, `retailer`, `wholesale`, `distributor` (the four spoken categories). The agent's own `caller_type` variable currently allows only direct customer / retailer / distributor — add `wholesale`, and send `individual` for a direct/personal-use caller.
2. **`store_type` and `area`** are new optional inputs to `save_request`; for a retailer they decide the retail Customer Group, so collect them.
3. **`items` must be ERPNext item codes** (e.g. `SASB-50INR-PACK-10`), not spoken product names.
4. **Quote after saving.** `upsert_quote` needs the caller on record; for a new caller, collect name + number and call `save_request` with the items (it returns the same figures under `quote`).
5. **A delivery pincode** is needed to quote a new caller (GST depends on the state) — pass it as `ship_to_pincode` or inside `address`.
6. **No call-log tools.** Remove `create_call_log`, `update_call_log` and `update_call_log_conversation_ref`; set `summary`, `conversation_ref` and `preferences` as output variables instead — the call-ended webhook writes them.
7. **Remove** `check_transfer_hours` (timeapi.io) and `route_to_*` (httpbin); use `transfer_target`.

## Configuration (Sarvam Voice Agent Settings)

Seeded by `seed_sarvam_voice_agent_rules` (only into empty tables):

- **Voice Agent Records** — Default Lead Owner (blank = automation user), Callback Task Assignee (**not seeded — set it**), Callback Task Priority (High), Quotation Company (blank = global default), New Deal Status (Qualification).
- **Caller Categories** — individual → Individual @ Standard Selling (default); wholesale, distributor → Commercial (default, no price list); retailer → the five retail groups (no default — flagged for review).
- **Pack Items** — SASB-50INR-PACK-4/10/20 → Individual only, Next Day Shipping.
- **Live Transfer** — 10:00–20:00, Mon–Sat, Asia/Kolkata, callers on record only; Kalpana +918248207671, Sravya +918106557040, Vinod +918122586261.

## Data notes

- On the dev site, `+919840456658` (Mahaveer Agencies - Ramapuram) also matches CRM Lead `CRM-LEAD-2026-04241` ("Rakesh", Converted, created 2026-11-02), so it resolves as Lead + Customer, not Customer-only. The same number is `test_caller_gate`'s blocked test number, which is why 3 of those tests error on dev (they fail identically without this change).
- ERPNext CRM Settings (the FCRM↔ERPNext integration) is disabled on dev, so Quotations have no `crm_deal` field; a Lead's Quotation is addressed to its `CRM Deal` directly. If the integration is enabled, `crm_deal` is filled as well.
