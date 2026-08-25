# Frappe JSON Fixtures Registry

Frappe JSON fixtures (such as Custom Fields, Property Setters, Workflows, etc.) do not natively support inline comments. To maintain transparency and adherence to our Business Blueprint, all structural changes to these JSON files must be documented here.

## Active Fixtures Log

| Date       | Target Fixture / Component                     | Business Rule Reference | Rationale                                                                 |
|------------|------------------------------------------------|-------------------------|---------------------------------------------------------------------------|
| 2026-08-25 | `Custom Field: Delivery Note-transporter`        | `[BR-LOG-001]`          | Added Supplier link (is_transporter=1) for 3PL logistics dispatch flow.   |
| 2026-08-25 | `Custom Field: Sales Invoice-lr_no`              | `[BR-LOG-002]`          | Replicated LR No from Delivery Note to synchronize line-haul dispatch.  |
| 2026-08-25 | `Print Format: Ecommerce Packing Slip`           | `[BR-PAC-001]`          | Created 4x6 label format suppressing pricing info for security.         |

*(Agents: Prepend new rows to this table whenever modifying structural JSON fixtures.)*
