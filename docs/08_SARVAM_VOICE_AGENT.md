# Manual 08 — Sarvam Inbound Voice Agent: Server Methods

**Files**: `voice_agent.py`, `lead_address_link.py`, `sarvam_telephony.py` (`handle_inbound_webhook`), `doctype/sarvam_voice_agent_settings/`, `doctype/sarvam_transfer_executive/`, `doctype/sarvam_caller_category/`, `doctype/sarvam_pack_item/`, `patches/v1_0/seed_sarvam_voice_agent_rules.py`, `patches/v1_0/seed_sarvam_address_list_limit.py`, `tests/test_voice_agent.py`
**Rules**: `[BR-TEL-006]`, `[BR-TEL-007]`, `[BR-CRM-004]`–`[BR-CRM-008]` (see `.agents/rules/business_blueprint.md`)
**Sample responses**: [`docs/samples/voice_agent_samples.json`](samples/voice_agent_samples.json) — every case below, generated from real calls on the dev site (the record names in it come from a rolled-back session).

---

## Why

The "Sravi Enterprises Customer Care" agent used to run ~16 start/end-of-call tools plus ~16 generic ERPNext tools and orchestrate CRM work itself. That caused repeated lookups, arithmetic mistakes (it quoted 47.62 × 10 = 476.20 for a pack whose price is 476.25, and 48 shipping where the rule charges 60) and half-finished multi-step saves. Each job is now **one call**; the agent only reads back what the server returns.

## Endpoints

All are `POST /api/method/core_customizations.core_customizations.voice_agent.<method>`, `allow_guest` and authenticated by `key` = `Sarvam Voice Agent Settings.webhook_secret` (same as `caller_gate.check`). Responses use the standard `{"message": {...}}` envelope.

**Sending the key.** The shared secret (`Sarvam Voice Agent Settings.webhook_secret`) is accepted from the first of these that carries it — for every method here, `caller_gate.check`, and both call webhooks (`handle_inbound_webhook`, `handle_outbound_webhook`):

1. a `key` **form field** (`application/x-www-form-urlencoded` / multipart) or a `key` field in a **JSON body**;
2. the **URL query string**, `?key=<secret>` — works with a JSON body too (Frappe builds a JSON request's arguments from the body alone, so the server reads the query string off the request itself);
3. the **`X-Webhook-Key` request header**.

It is compared in constant time; a wrong, empty or missing key is `403 PermissionError: Unauthorized request`. The key is never logged — it is stripped from the payload and the headers before an Integration Request is written.

```bash
# JSON body, key in the URL
curl -X POST 'https://<site>/api/method/core_customizations.core_customizations.voice_agent.save_request?key=<secret>' \
  -H 'Content-Type: application/json' -d '{"phone": "+919876543210", "name": "Ravi", "caller_type": "individual"}'
# JSON body, key in the body
curl -X POST 'https://<site>/api/method/core_customizations.core_customizations.voice_agent.save_request' \
  -H 'Content-Type: application/json' -d '{"key": "<secret>", "phone": "+919876543210", "name": "Ravi", "caller_type": "individual"}'
# JSON body, key in the header
curl -X POST 'https://<site>/api/method/core_customizations.core_customizations.voice_agent.save_request' \
  -H 'Content-Type: application/json' -H 'X-Webhook-Key: <secret>' -d '{"phone": "+919876543210", "name": "Ravi", "caller_type": "individual"}'
```

Every method first runs `caller_gate.evaluate(phone)`. A blocked or foreign caller gets only:

```json
{"message": {"allowed": false, "reason": "BLOCKED_LIST", "message": "This caller is on the blocked list."}}
```

— no data, no writes. Numbers match on their last 10 digits, so `98411 02004`, `+91 98411-02004`, `919841102004` and `09841102004` are the same caller.

| Method | Replaces | Inputs |
|---|---|---|
| `call_started` (webhook) | `check_blocked`, `lookup_caller_lead`, `lookup_caller_contact`, `lookup_lead_organization`, `lookup_contact_customer`, `fetch_caller_preferences`, `fetch_user_metadata`, `create_call_log`, `get_saved_addresses` | Sarvam's call-start payload: `user_phone_number`, `interaction_id`, `agent_phone_number`; `key` in the query string |
| `caller_context` | same as above, as a tool instead of a webhook | `phone`, `key`, `call_id` (optional — Sarvam's `interaction_id`) |
| `get_caller_preferences` / `set_caller_preferences` | `fetch_caller_preferences` | `phone`, `key`; set also takes `preferences` (JSON object) and `merge` (default 1) |
| `upsert_quote` | the agent's own price/tax/shipping arithmetic | `phone`, `key`, `items` = `[{"item_code", "qty"}]`, `address_name` or `ship_to_pincode` (optional) |
| `save_request` | the chain of create-lead / create-deal / create-quotation / create-task calls | `phone`, `key`, `name`, `caller_type`, `store_type`, `area`, `organization`, `items`, `address_name` **or** `address` + `city` + `pincode` (+ `state`), `whatsapp_number`, `notes`, `ship_to_pincode` |
| `transfer_target` | `check_transfer_hours` (timeapi.io), `route_to_*` (httpbin) | `phone`, `key` |
| call-ended webhook (`sarvam_telephony.handle_inbound_webhook`, unchanged URL) | `update_call_log`, `update_call_log_conversation_ref` | Sarvam's call-end payload; reads `output_agent_variables.summary`, `.conversation_ref`, `.preferences` |

### Sarvam configuration

- **Call started** webhook: `<site>/api/method/core_customizations.core_customizations.voice_agent.call_started?key=<webhook_secret>`
- **Call ended** webhook: `<site>/api/method/core_customizations.core_customizations.sarvam_telephony.handle_inbound_webhook?key=<webhook_secret>` (as before)

Both payload shapes are still unconfirmed against a real delivery — every delivery is logged as an Integration Request ("Sarvam Call Started" / "Sarvam Inbound Call"), so check the first real ones and adjust the key names at the top of `voice_agent.py` (`CALLER_PHONE_KEYS`, `CALL_ID_KEYS`, `SUMMARY_KEYS`, `CONVERSATION_REF_KEYS`) if Sarvam names them differently.

## Saved addresses (`[BR-CRM-008]`)

`caller_context` / `call_started` return `addresses` — the caller's saved Address records, from their **Customer** if they have one, otherwise from their **CRM Lead**:

```json
"addresses": [
  {"name": "…-Shipping", "address_title": "…", "address_type": "Shipping", "address_line1": "12 Godown Street", "address_line2": null,
   "city": "Hyderabad", "state": "Telangana", "pincode": "500062", "is_primary_address": 0, "is_shipping_address": 1}
]
```

- Enabled only; shipping-preferred first, then primary, then most recently modified; at most `address_list_limit` (5). No Customer/Lead or none saved → `[]`. Blocked/foreign → no `addresses` key at all.
- Offer these to a returning caller and pass the chosen one back as **`address_name`** to `upsert_quote` / `save_request` — it wins over any spoken address or pincode. A name that isn't the caller's own (another customer's, or a disabled one) returns `ADDRESS_NOT_ON_RECORD` and saves nothing.
- A new caller's spoken address (`address` + `city` + `pincode`; `state` is worked out from the pincode when not given) is saved as a Shipping Address linked to their CRM Lead, reused if they give it again, and returned in `save_request`'s `address`. Without a city or pincode the request is still saved, with an `ADDRESS_NOT_SAVED: missing …` warning. The `Address:` line in the Lead's `company_description` is still written.
- When that Lead becomes a Customer (by hand in Desk, or through the CRM integration), its Addresses are linked to the Customer too (`lead_address_link.py`), so the caller still sees them. The Lead is taken from the Customer's `crm_deal`, else a Contact linked to both, else the CRM Lead on its mobile number — only when exactly one matches. Several candidates → nothing is linked and Error Log gets one entry, *"Lead Address Link: could not decide the CRM Lead for Customer …"*, naming them.

**GST and saved addresses.** For a Customer, `address_name` becomes the Quotation's `shipping_address_name` and India Compliance works out the place of supply as it does in Desk. Which address it reads is a site setting — Accounts Settings › *Determine Address Tax Category From*, currently **Billing Address** on dev — so today a Customer's GST follows their **billing** address whichever shipping address is chosen (sample `upsert_quote.hyderabad_shipping_address_on_billing_basis_site`: CGST/SGST although it ships to Hyderabad). Set it to *Shipping Address* and the chosen address decides (tested: same GST as quoting that pincode, both in-state and out-of-state). For a lead's CRM Deal quotation, the Address's pincode decides directly.

## Outcomes the agent must handle

**`upsert_quote`** → `status: "quoted"` with `net_total`, `taxes: [{type: CGST|SGST|IGST, rate, amount}]`, `shipping`, `rounding_adjustment`, `grand_total`, `rounded_total`, **`total_to_say`** (read this one aloud), or `status: "error"` with `error`:

| `error` | Meaning / what the agent says |
|---|---|
| `NOT_ON_RECORD` | Caller has no Lead/Customer yet — call `save_request` first (it quotes the same items) |
| `QUOTE_NOT_AVAILABLE` | Category isn't quoted by the agent (wholesale, distributor, retailer) — team calls back |
| `PACK_NOT_AVAILABLE` | Packs of 4/10/20 are for Individual customers only |
| `PINCODE_REQUIRED` | Ask for the delivery pincode, call again with `ship_to_pincode` |
| `ADDRESS_NOT_ON_RECORD` | The `address_name` isn't this caller's — ask for the address again (`message` says so) |
| `PRICE_NOT_FOUND` / `ITEM_NOT_AVAILABLE` / `MIXED_SHIPPING` / `INVALID_ITEMS` | Can't quote these items — team calls back |

**`save_request`** → `status`:

| `status` | Meaning |
|---|---|
| `saved` | New Lead created (+ callback Task; + Deal and draft Quotation when quotable items were given), or an existing Customer's Deal/Quotation |
| `duplicate` | The caller already has a Lead — **no new Lead was created**; `lead` is the existing one, `message` is the `DUPLICATE_LEAD:` token, and the request was recorded on a callback Task against it |
| `blocked` | Caller is blocked/foreign (or became so mid-call — the `CALLER_BLOCKED:` guard fired); nothing saved |
| `error` | `NAME_REQUIRED`, `PHONE_REQUIRED`, `INVALID_ITEMS`, `ADDRESS_NOT_ON_RECORD` or `ADDRESS_INVALID` — nothing was saved; ask and retry |

`warnings` may carry `CUSTOMER_GROUP_NEEDS_REVIEW: retailer`, `UNKNOWN_CATEGORY: <value>` or `ADDRESS_NOT_SAVED: missing city` — informational, also written on the Task for the team.

**`transfer_target`** → `open: true` with `target` (then `then[]` in order), or `open: false`, `decision: "CALLBACK"`, `reason` `OUTSIDE_HOURS` / `NOT_ON_RECORD` / `NO_EXECUTIVES`.

## Changes to the agent's required inputs

1. **`caller_type` values** are `individual`, `retailer`, `wholesale`, `distributor` (the four spoken categories). The agent's own `caller_type` variable currently allows only direct customer / retailer / distributor — add `wholesale`, and send `individual` for a direct/personal-use caller.
2. **`store_type` and `area`** are new optional inputs to `save_request`; for a retailer they decide the retail Customer Group, so collect them.
3. **`items` must be ERPNext item codes** (e.g. `SASB-50INR-PACK-10`), not spoken product names.
4. **Quote after saving.** `upsert_quote` needs the caller on record; for a new caller, collect name + number and call `save_request` with the items (it returns the same figures under `quote`).
5. **A delivery pincode** is needed to quote a new caller (GST depends on the state) — pass it as `ship_to_pincode` or inside `address`.
6. **No call-log tools.** Remove `create_call_log`, `update_call_log` and `update_call_log_conversation_ref`; set `summary`, `conversation_ref` and `preferences` as output variables instead — the call-ended webhook writes them.
7. **Remove** `check_transfer_hours` (timeapi.io) and `route_to_*` (httpbin); use `transfer_target`.
8. **Remove `get_saved_addresses`.** Read `addresses` from `caller_context`, pass the chosen one as `address_name`.
9. **Collect `city` and `pincode`** with a new caller's address so it can be saved as a real Address (`state` is optional).

## Configuration (Sarvam Voice Agent Settings)

Seeded by `seed_sarvam_voice_agent_rules` (only into empty tables):

- **Voice Agent Records** — Default Lead Owner (blank = automation user), Callback Task Assignee (**not seeded — set it**), Callback Task Priority (High), Quotation Company (blank = global default), New Deal Status (Qualification), Saved Addresses Returned (5).
- **Caller Categories** — individual → Individual @ Standard Selling (default); wholesale, distributor → Commercial (default, no price list); retailer → the five retail groups (no default — flagged for review).
- **Pack Items** — SASB-50INR-PACK-4/10/20 → Individual only, Next Day Shipping.
- **Live Transfer** — 10:00–20:00, Mon–Sat, Asia/Kolkata, callers on record only; Kalpana +918248207671, Sravya +918106557040, Vinod +918122586261.

## Data notes

- `+919840456658` (Mahaveer Agencies - Ramapuram) resolves as Customer-only (`lead: null`) now that the stray "Rakesh" Lead on that number has been deleted. Three `test_caller_gate` tests still error on dev, now because its `_new_lead` helper creates Leads without the mandatory `lead_owner` (unrelated to this work).
- ERPNext CRM Settings (the FCRM↔ERPNext integration) is disabled on dev, so Quotations have no `crm_deal` field; a Lead's Quotation is addressed to its `CRM Deal` directly. If the integration is enabled, `crm_deal` is filled as well.
