# Frappe JSON Fixtures Registry

Frappe JSON fixtures (such as Custom Fields, Property Setters, Workflows, etc.) do not natively support inline comments. To maintain transparency and adherence to our Business Blueprint, all structural changes to these JSON files must be documented here.

## Active Fixtures Log

| Date       | Target Fixture / Component                     | Business Rule Reference | Rationale                                                                 |
|------------|------------------------------------------------|-------------------------|---------------------------------------------------------------------------|
| 2026-11-03 | `Custom Field: CRM Lead-custom_caller_category` | `[BR-CRM-005]` | Category the caller gave the voice agent (individual/retailer/wholesale/distributor); mapped to a Customer Group via Sarvam Voice Agent Settings > Caller Categories. Data, not Select, so the allowed values live in settings. |
| 2026-11-03 | `Custom Field: CRM Lead-custom_store_type` | `[BR-CRM-005]` | Store type the caller gave (GT, Pharmacy, Petty Shop, ...); decides the retail Customer Group with area. |
| 2026-11-03 | `Custom Field: CRM Lead-custom_caller_preferences` | `[BR-CRM-007]` | JSON voice-agent preferences (preferred_language, preferred_flow, ...) read/written by voice_agent.get/set_caller_preferences, replacing free-text comments. |
| 2026-11-03 | `Custom Field: Contact-custom_caller_preferences` | `[BR-CRM-007]` | Same, for a Customer-only caller who has a Contact but no CRM Lead. |
| 2026-11-03 | `Custom Field: CRM Call Log-custom_conversation_ref` | `[BR-TEL-007]` | Sarvam conversation reference, written by the call-ended webhook (replaces the agent's update_call_log_conversation_ref tool). |
| 2026-11-03 | `Custom Field: CRM Call Log-custom_agent_variables` | `[BR-TEL-007]` | The agent's output variables as delivered by the call-ended webhook, stored whole so a renamed Sarvam key is never lost. |
| 2026-11-01 | `Property Setter: CRM Call Log-telephony_medium-options` | `[BR-TEL-002]` | Added "Sarvam" to the telephony_medium Select options so outbound Sarvam AI calls can be logged with the correct medium. |
| 2026-08-25 | `Custom Field: Delivery Note-transporter`        | `[BR-LOG-001]`          | Added Supplier link (is_transporter=1) for 3PL logistics dispatch flow.   |
| 2026-08-25 | `Custom Field: Sales Invoice-lr_no`              | `[BR-LOG-002]`          | Replicated LR No from Delivery Note to synchronize line-haul dispatch.  |
| 2026-08-25 | `Print Format: Ecommerce Packing Slip`           | `[BR-PAC-001]`          | Created 4x6 label format suppressing pricing info for security.         |

*(Agents: Prepend new rows to this table whenever modifying structural JSON fixtures.)*
