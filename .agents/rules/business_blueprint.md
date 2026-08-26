# Business Blueprint & Rule Registry

This document serves as the single source of truth for all domain logic and operational business rules implemented in the `core_customizations` app. All Python, JS, and JSON Fixture changes must strictly map back to one of the following Business Rules `[BR-XXX]`.

## Epic 1: Dual Sales & Fulfillment Architecture
* **`[BR-SALES-001]` Wholesale Dispatch-First Flow**: For B2B/Wholesale transactions, a `Delivery Note` is strictly required before a `Sales Invoice` can be created. The Delivery Note is responsible for all stock ledger movements and batch allocations. The subsequent Sales Invoice must not update stock (`update_stock = 0`).
* **`[BR-SALES-002]` Retail POS Counter Flow**: For Over-The-Counter transactions, the `POS Invoice` handles immediate stock and payment. The end-of-day POS Closing Entry creates a consolidated `Sales Invoice` with `update_stock = 1`, completely bypassing the Delivery Note requirement.

## Epic 2: Sales Returns & Credit Notes
* **`[BR-RET-001]` Wholesale Return Flow**: Stock returns must be processed via a `Delivery Note` with `is_return = 1` (reverting stock), while financial refunds are handled via a separate `Sales Invoice` Credit Note with `is_return = 1` and `update_stock = 0`. Credit Notes bypass the forward Delivery Note requirement.
* **`[BR-RET-002]` POS Return Flow**: Immediate POS refunds are handled by a `POS Invoice` with `is_return = 1`, which instantly restocks the godown and refunds the customer before shift consolidation.

## Epic 3: 3PL Logistics & Transporter Management
* **`[BR-LOG-001]` Customer Transporter Defaults**: When creating a Delivery Note, Transporter, Origin Hub, and Destination Godown must auto-populate from the Customer's primary defaults.
* **`[BR-LOG-002]` Sync LR Details**: Transporter Lorry Receipt (LR) Details, Vehicle No, and Receipt Image captured on the Delivery Note must synchronize strictly across both the Delivery Note and linked Sales Invoice.

## Epic 4: Indian GST E-Way Bill Compliance
* **`[BR-EWB-001]` Single E-Way Bill Rule**: Only a single E-Way Bill must be generated (against the Tax Invoice) for the entire transit.
* **`[BR-EWB-002]` 50km First-Mile Auto Exemption (Rule 138(3))**: When stock moves from 3PL Godown to Transporter Hub within 50km via Auto/Feeder, Part A is mandatory but Part B (Vehicle No) is legally exempt.
* **`[BR-EWB-003]` Consignor Part B Authority**: If the transporter fails to update Part B for the line-haul truck, the 3PL dispatcher retains the legal authority and responsibility to update Part B directly from the ERPNext portal using the issued LR number.

## Epic 5: Inventory Guardrails
* **`[BR-INV-001]` Single Warehouse Confinement**: A single `Delivery Note` is strictly confined to dispatching goods from one single warehouse. Mixed warehouse dispatches on the same document are prohibited and must trigger validation errors.

## Epic 6: Packing Slips & Carton Management
* **`[BR-PAC-001]` Draft Carton Packing Slips**: Generating a packing slip creates it in a `Draft` state linked to specific items. Draft packing slips must be excluded from the final Delivery Note print format.
* **`[BR-PAC-002]` Bulk Submission Synchronization**: Submitting a Delivery Note must automatically submit all attached `Draft` packing slips. Cancelling a Delivery Note must auto-cancel all submitted packing slips.

## Epic 7: Document Dependency & Cancellation Guardrails
* **`[BR-CAN-001]` Strict Reverse Cancellation Sequence**: Cancellation must strictly follow downstream reversal: `Payment Entry` -> `Sales Invoice` -> `Delivery Note` -> `Sales Order`. Attempting to cancel an upstream document with an active downstream dependency must be blocked by a `LinkValidationError`.

## Epic 8: Purchase & Inbound Logistics
* **`[BR-PUR-001]` 3PL Inbound Receipt Dependency**: When a Purchase Invoice contains any 3PL Item (custom_3pl_item = 1), it must not update stock directly. Every 3PL Item row must be billed against a linked Purchase Receipt to ensure the 3PL warehouse handles the actual inbound stock movement.

## Epic 9: Automated Procurement (MR → PO Automation)
* **`[BR-PROC-001]` Supplier Source of Truth**: The authoritative source for an Item's supplier is the **"Item Supplier"** child table on the Item master (Purchasing tab), not Item Default. All automation logic must query `tabItem Supplier` for supplier resolution.
* **`[BR-PROC-002]` Draft PO Generation**: All auto-generated Purchase Orders must remain in **Draft** state (`docstatus = 0`) for mandatory human review and approval before submission. The system must never auto-submit a PO.
* **`[BR-PROC-003]` Single-Supplier Constraint**: The MR → PO automation is **only triggered when every item on the Material Request has exactly one (1) supplier** configured in its Item Supplier table. If any item has zero or more than one supplier, the automation must abort and log a descriptive error message, requiring the purchasing team to create the PO manually.
* **`[BR-PROC-004]` Warehouse Propagation**: The `set_warehouse` from the originating Material Request must be explicitly carried over to the auto-generated Purchase Order so that the shipping address resolves to the correct Warehouse delivery address on the `GST Purchase Order` print format.
* **`[BR-PROC-005]` Email Notification on PO Creation**: Upon successful draft PO creation, email notifications must be dispatched to both (a) the Supplier's primary contact email and (b) the Company's purchasing email. If neither is found, the notification falls back to the System Manager.
* **`[BR-PROC-006]` Idempotency Guard**: If a Purchase Order already exists that references the originating Material Request (checked via `Purchase Order Item.material_request`), the automation must detect this and silently exit without creating a duplicate PO.
