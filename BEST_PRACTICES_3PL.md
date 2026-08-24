# ERPNext 3PL & Inventory Best Practices

This document outlines the architectural best practices, hard constraints, and recommended workflows for managing bulk inventory (Cartons/Boxes) alongside retail operations (Point of Sale) in ERPNext.

---

## 1. Unit of Measure (UOM) Configuration

### The Golden Rule
**Always make your Primary (Default) UOM the SMALLEST unit you will ever sell.**

- **Primary UOM**: `Nos` (or Pieces)
- **Secondary UOM**: `Box` or `Carton` (defined in the UOM Conversion Factors table, e.g., 1 Box = 400 Nos).

#### Why? (The POS Constraint)
The ERPNext Point of Sale (POS) interface is hardcoded for rapid checkout. When a cashier scans a barcode, the POS cart **always defaults to the Primary UOM**. 
- **What NOT to do**: Do not make `Box` your Primary UOM. If you do, scanning an item at retail will add a full Box (400 pieces) to the cart. The cashier would have to manually edit the row, change the UOM to `Nos`, and adjust the quantity for every single customer. This completely breaks the retail experience.
- **The Wholesale Workflow**: Wholesale orders (Purchase Receipts, Delivery Notes) are processed in the back office where data entry is deliberate. A warehouse manager can easily select `Box` from the UOM dropdown and type `Qty = 2`. ERPNext will automatically do the math in the background and update the ledger by `800 Nos`.

---

## 2. Tracking Cartons: Batches vs. Serial Numbers

When dealing with bulk inbound cartons that you want to track uniquely in your 3PL Godown, you must choose the right tracking mechanism.

### The Recommended Approach: Batch Numbers
**Use Batch Numbers to track physical boxes.**
- **Setup**: Base UOM is `Nos`. Check `Has Batch No` (Leave `Has Serial No` unchecked).
- **Inbound**: When you receive 1 Box, you assign it a Batch Number (e.g., `CRT-001`). ERPNext records that `CRT-001` contains exactly 400 Nos.
- **Outbound (Wholesale)**: You sell 1 Box. You select Batch `CRT-001`, and the batch depletes to 0.
- **Outbound (Retail)**: A customer buys 5 loose `Nos`. You select Batch `CRT-001`, and the batch dynamically depletes to 395 Nos remaining.
- **Rationale**: This is the most flexible approach. It allows you to seamlessly buy in boxes and sell in loose quantities without having to manually "unpack" anything in the system.

### What NOT to do: Serializing the Base UOM
- **Do not** check `Has Serial No` if your base UOM is `Nos` and you want to track the physical Box. 
- **Rationale**: In ERPNext, Serial Numbers are strictly tied to the Base UOM. If you receive 1 `Box` (Conversion Factor: 400), ERPNext will aggressively generate **400 individual Serial Numbers**, not 1. 

### The Alternative: Serializing at the Box Level
If compliance absolutely requires a Serial Number for the physical carton, you must create a separate Item Code where the Base UOM is `Box` and `Has Serial No` is checked.
- **The Catch**: If a retail customer wants to buy 5 loose items, you cannot sell them directly. You must first create a **Stock Entry (Repack)** to legally "open" the box in the system (consuming 1 Serialized Box and outputting 400 loose, non-serialized `Nos` of a different item code).

---

## 3. Migrating Existing Stock

If you have existing inventory that is currently untracked (or batched) and you want to make it serialized/batch-compliant:

- **What NOT to do**: Do not attempt to simply check the `Has Serial No` or `Has Batch No` box on the existing Item Master. If there are any Stock Ledger Entries (SLE) tied to that item, ERPNext explicitly blocks you from changing these tracking properties to preserve accounting integrity.
- **What to do**: 
  1. Create a "V2" Item Code (e.g., `SASTRY-BALM-12.6-V2`) with the correct tracking settings.
  2. Create a **Stock Entry (Purpose: Repack)**.
  3. **Source Row**: Consume the old item (entire quantity).
  4. **Target Row**: Generate the new "V2" item. The system will prompt you to generate the required serials/batches here.
  5. Check `Disabled` on the old Item Master so it is no longer used.

---

## 4. The Outbound Billing Flow (SO -> DN -> SI)

In a Dual Sales Architecture, the actual stock deduction happens at the **Delivery Note (DN)**. 

1. **Sales Order (SO)**: No batches or serial numbers are selected here. It is purely a financial commitment to supply X amount of stock.
   - **UOM Note**: The SO is typically raised in the Primary UOM (`Nos`) by the sales team (e.g., Qty = 800 Nos).
2. **Delivery Note (DN)**: The physical dispatch. The warehouse dispatcher MUST select the specific Batch/Serial Number being loaded onto the truck (via Barcode Scanner or Auto-Fetch). ERPNext rigorously validates that this specific stock exists in the selected warehouse before deducting it.
   - **Cross-Document UOM Compatibility**: When you create a DN from an SO, the DN initially pulls the `Nos` UOM. However, the dispatcher can natively change the UOM on the DN to `Box` and change the Qty to `2`. ERPNext handles this natively without custom code. The system tracks fulfillment against the SO using the underlying **Stock UOM Qty** (800 Nos). As long as the Stock Qty matches, the SO will be marked as fully delivered, regardless of the transactional UOM used on the DN!
3. **Sales Invoice (SI)**: When the DN is converted to an SI, the Batch/Serial Numbers and UOMs are automatically copied over. Because this app utilizes `update_stock = 0` on the SI, the invoice acts purely as an accounting document for billing and warranty printing, preventing double-deduction of stock.
