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

**Payload key names — what's confirmed.** No real call-started or call-ended delivery has reached the dev site yet (0 "Sarvam Call Started" / "Sarvam Inbound Call" Integration Requests, no Incoming Call Logs), so none of these is confirmed by a real delivery:

| Constant in `voice_agent.py` | Keys tried | Source |
|---|---|---|
| `CALLER_PHONE_KEYS` | `user_phone_number`, `phone`, `caller_number`, `from` | `user_phone_number` is from Sarvam's published inbound payload schema (the one `handle_inbound_webhook` was written against); the rest are guesses for the call-started payload |
| `CALL_ID_KEYS` | `interaction_id`, `call_id` | `interaction_id` from that schema; `call_id` a guess |
| `SUMMARY_KEYS` | `summary`, `call_summary` | Guesses — these are keys of `output_agent_variables`, i.e. **whatever the agent's own output variables are named**: name them `summary`, `conversation_ref` and `preferences` in the agent and they match |
| `CONVERSATION_REF_KEYS` | `conversation_ref`, `conversation_id` | Same — agent-defined output variables |
| `PREFERENCES_KEY` | `preferences` | Same |

The call-ended payload's transcript (`interaction_transcript`, a list of `{role, en_text}` turns, per the schema) is saved as **one FCRM Note referencing the Call Log**, titled *"Call transcript: <date>"*; a redelivery updates that Note rather than adding another (it used to be a Comment). The summary stays a separate Note, linked from the Call Log's `note` field.

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

**`upsert_quote`** → `status: "quoted"` with `net_total`, `taxes: [{type: CGST|SGST|IGST, rate, amount}]`, **`gst_percent`**, **`gst_amount`**, `shipping`, `rounding_adjustment`, `grand_total`, `rounded_total`, **`total_to_say`**, or `status: "error"` with `error`.

**Which price list.** The first of these with a list is used — never a guess: (1) the Customer's own `default_price_list`, (2) its Customer Group's `default_price_list`, (3) the Caller Categories fallback in Sarvam Voice Agent Settings for the caller's category (a new caller / lead; or a Customer whose group maps to a category — the row for that group if it has a list, else the category's default row; Individual → Standard Selling). Nothing found → `NO_PRICE_LIST` for a Customer (`QUOTE_NOT_AVAILABLE` for a lead's category). The quote returns `price_list` and `price_list_source` (`customer` / `customer_group` / `settings`) for logging — the agent doesn't speak them. A chosen list that is disabled, not a selling list, or in another currency than the quotation is refused (`PRICE_LIST_UNUSABLE`, with `reason`) — never swapped for another list; an item with no Item Price in it is `PRICE_NOT_FOUND`, again with no fallback. Changing the settings lists never changes the quote of a Customer who has a list of its own.

**What the agent reads aloud:** only "GST", `gst_percent`, `gst_amount` and `total_to_say` — e.g. *"GST at 5 percent is ₹23.81; the total is ₹560."* Never IGST/CGST/SGST, and never a sum it works out itself. `gst_percent` is the GST rows' rates summed (2.5 + 2.5, or 5); `gst_amount` is their amounts summed, each already rounded by the Quotation (so an in-state quote can be a paisa above the same out-of-state one — 11.91 + 11.91 = 23.82 vs 23.81 — while `total_to_say` rounds to the same rupee). `taxes` stays for staff and documents. The same fields are in `save_request`'s `quote`.

Errors:

| `error` | Meaning / what the agent says |
|---|---|
| `NOT_ON_RECORD` | Caller has no Lead/Customer yet — call `save_request` first (it quotes the same items) |
| `QUOTE_NOT_AVAILABLE` | Category isn't quoted by the agent (wholesale, distributor, retailer) — team calls back |
| `PACK_NOT_AVAILABLE` | Packs of 4/10/20 are for Individual customers only |
| `PINCODE_REQUIRED` | Ask for the delivery pincode, call again with `ship_to_pincode` |
| `ADDRESS_NOT_ON_RECORD` | The `address_name` isn't this caller's — ask for the address again (`message` says so) |
| `NO_PRICE_LIST` | No list on the Customer, its group or the settings fallback — team calls back |
| `PRICE_LIST_UNUSABLE` | The caller's list is disabled / not for selling / in another currency (`reason`) — team calls back |
| `PRICE_NOT_FOUND` / `ITEM_NOT_AVAILABLE` / `MIXED_SHIPPING` / `INVALID_ITEMS` | Can't quote these items — team calls back |

**`save_request`** → `status`:

| `status` | Meaning |
|---|---|
| `saved` | New Lead created (+ callback Task; + Deal and draft Quotation when quotable items were given), or an existing Customer's Deal/Quotation |
| `duplicate` | The caller already has a Lead — **no new Lead was created**; `lead` is the existing one, `message` is the `DUPLICATE_LEAD:` token, and the request was recorded on a callback Task against it |
| `blocked` | Caller is blocked/foreign (or became so mid-call — the `CALLER_BLOCKED:` guard fired); nothing saved |
| `error` | `NAME_REQUIRED`, `PHONE_REQUIRED`, `INVALID_ITEMS`, `ADDRESS_NOT_ON_RECORD` or `ADDRESS_INVALID` — nothing was saved; ask and retry |

`warnings` may carry `CUSTOMER_GROUP_NEEDS_REVIEW: <category>` / `UNKNOWN_CATEGORY: <value>` (only for a caller with **no Customer**, or a Customer whose group isn't mapped in Caller Categories — an existing Customer with a mapped group, e.g. Mahaveer → Commercial → wholesale, is already classified and never warned) or `ADDRESS_NOT_SAVED: missing city` — informational, also written on the Task for the team.

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

## Persistent test records (dev only)

Kept on the dev site for automated Sarvam test calls — do not delete; never created on production. The unit tests use their own numbers (`+9170000011xx`) and `VA Unit …` names, rolled back after each test, and check that they never match these.

| Record | Name | Details |
|---|---|---|
| Customer | `VA Test Individual Customer` | Group Individual, price list Standard Selling, Unregistered |
| Contact | `VA Test Individual Customer-VA Test Individual Customer` | Mobile **+917000000104**, linked to the Customer |
| Address (Billing, primary) | `VA Test Individual Customer Chennai-Billing` | 1 Test Street, Chennai, Tamil Nadu 600128 |
| Address (Shipping) | `VA Test Individual Customer Hyderabad-Shipping` | 12 Test Godown Road, Hyderabad, Telangana 500062 |
| Blocked Contact | `7000000199` | **+917000000199**, enabled — returns `BLOCKED_LIST` from the real list |
| Price List | `VA Test Individual Pricelist` | Selling, INR — PACK-4 185, PACK-10 465, PACK-20 890, SASB-12.6 ML 44 |
| Price List | `VA Test Group Pricelist` | Selling, INR — PACK-4 188, PACK-10 470, PACK-20 895, SASB-12.6 ML 45 |
| Customer Group | `VA Test Individual Group` | Parent All Customer Groups, default list `VA Test Group Pricelist` |
| Customer (own list) | `VA Test Custom List Customer` | Group Individual, list `VA Test Individual Pricelist`; Contact **+917000000105**; Billing Chennai 600128, Shipping Hyderabad 500062 → quotes `customer` |
| Customer (group list) | `VA Test Group List Customer` | Group `VA Test Individual Group`, **no list** on the Customer; Contact **+917000000106**; same two addresses → quotes `customer_group` for SASB-12.6 ML; **packs are refused** (`PACK_NOT_AVAILABLE` — packs are Individual-group only) |
| Customer (no list) | `VA Test No List Customer` | Group Individual, **no list** on Customer or group; Contact **+917000000107**; same two addresses → quotes `settings` (Standard Selling) |

`Customer.default_price_list` is mandatory on this site, so the two "no list" customers had it blanked directly in the database (as a legacy record would be); saving them in Desk will ask for a list again. Contact names follow `<customer>-<customer>`, addresses `<customer> Chennai-Billing` / `<customer> Hyderabad-Shipping`.

## Data notes

- `+919840456658` (Mahaveer Agencies - Ramapuram) resolves as Customer-only (`lead: null`) now that the stray "Rakesh" Lead on that number has been deleted. Three `test_caller_gate` tests still error on dev, now because its `_new_lead` helper creates Leads without the mandatory `lead_owner` (unrelated to this work).
- ERPNext CRM Settings (the FCRM↔ERPNext integration) is disabled on dev, so Quotations have no `crm_deal` field; a Lead's Quotation is addressed to its `CRM Deal` directly. If the integration is enabled, `crm_deal` is filled as well.
