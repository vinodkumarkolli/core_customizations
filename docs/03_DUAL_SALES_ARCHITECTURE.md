# Manual 03 — Dual Sales Architecture: Wholesale & Retail Flows

**Business Rules**: `[BR-SALES-001]`, `[BR-SALES-002]`, `[BR-RET-001]`, `[BR-RET-002]`, `[BR-CAN-001]`  
**Files**: `sales_invoice.py`, `delivery_note.py`

---

## Overview

The system enforces two strictly separate sales fulfillment flows depending on the sales channel. These flows are **not interchangeable** — each has dedicated validation rules enforced on both the client and server.

```
┌─────────────────────────────────────────────────────────────┐
│  FLOW 1: Wholesale / B2B (Dispatch-First)                   │
│                                                             │
│  Sales Order → Delivery Note → Sales Invoice                │
│                (Stock moves)   (update_stock = 0)           │
│                     ↓                                       │
│              Packing Slips (4x6 Thermal Labels)             │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  FLOW 2: Retail / Over-the-Counter POS                      │
│                                                             │
│  POS Register → POS Invoice → POS Closing Entry             │
│                 (Stock + Pay)                               │
│                     ↓                                       │
│           Consolidated Sales Invoice (update_stock = 1)     │
└─────────────────────────────────────────────────────────────┘
```

---

## Flow 1: Wholesale / B2B (Dispatch-First)

### Principle (`[BR-SALES-001]`)
In the wholesale channel, the **Delivery Note** owns all stock movements. The Sales Invoice is purely a financial document and must **never** update stock (`update_stock = 0`).

### Step-by-Step

#### Step 1: Create a Sales Order
1. Go to **Selling → Sales Order → New**.
2. Select Customer, add items, set delivery date.
3. **Save and Submit**.

#### Step 2: Create a Delivery Note
1. From the Sales Order, click **Create → Delivery Note**.
2. Verify the **Source Warehouse** (must be a single warehouse — mixed warehouses are blocked by `[BR-INV-001]`).
3. Set transporter details via **Logistics → Transporter** if not auto-populated.
4. **Save and Submit**.
   - All Draft packing slips are auto-submitted.
   - Stock ledger moves at this point.

#### Step 3: Generate Packing Slips (before DN submission)
1. From the Delivery Note, click **Packing Slips → Generate** before submitting.
2. Submit individual slips or use **Submit All Draft Slips**.
3. Print labels via **Packing Slips → Print All Slips** for the dispatch team.

#### Step 4: Create a Sales Invoice
1. From the submitted Delivery Note, click **Create → Sales Invoice**.
2. **Critical**: Ensure `Update Stock` is **unchecked** (`update_stock = 0`). The system validates this.
3. Verify tax rows (GST) are correctly applied.
4. **Save and Submit**.
   - UPI QR code appears automatically on the print format for unpaid invoices.

#### Step 5: Capture LR Details (Post-Dispatch)
Once goods are handed over to the transporter and the LR is received:
1. Go back to the Delivery Note.
2. Click **Logistics → Update LR Details**.
3. Fill Vehicle No, LR No, upload LR image.
4. Click **Update** — fields sync across DN and SI; E-Way Bill Part B updates automatically.

### Validation Rules Enforced
- `[BR-SALES-001]`: Sales Invoice creation blocked if no submitted Delivery Note exists (except credit notes and POS).
- `[BR-INV-001]`: Delivery Note blocked if items span multiple warehouses.
- `[BR-SALES-001]`: `update_stock = 1` on a wholesale Sales Invoice is blocked by server validation.

---

## Flow 2: Retail / POS (Over-the-Counter)

See **[Manual 04 — Point of Sale](./04_POINT_OF_SALE.md)** for the complete POS setup and operations guide.

The key distinction: POS Invoices and the Consolidated Sales Invoice created by the POS Closing Entry are **exempt** from the Delivery Note requirement.

---

## Sales Returns & Credit Notes

### Wholesale Return Flow (`[BR-RET-001]`)

Returns in the wholesale channel require **two separate documents** — one to reverse stock, one to reverse financials:

#### Physical Stock Return
1. Go to the original **Delivery Note**.
2. Click **Create → Delivery Note** (return).
3. The return DN has `is_return = 1` and **negative quantities**.
4. Submit — this increases stock in the source warehouse and restores batch allocations.

#### Financial Credit Note
1. Go to the original **Sales Invoice**.
2. Click **Create → Return / Credit Note**.
3. The Credit Note has `is_return = 1` and `update_stock = 0`.
4. Submit — this reverses Accounts Receivable, revenue, and output GST.
5. No Delivery Note is required for return Credit Notes — validation is bypassed for `is_return = 1`.

### Retail / POS Return Flow (`[BR-RET-002]`)

1. In the POS UI, open the customer's original POS Invoice.
2. Click **Return** — a return POS Invoice is created with negative quantities.
3. The return immediately restocks the item and processes the customer refund.
4. The POS Closing Entry at end-of-day consolidates returns into net settlement.

---

## Document Cancellation Sequence (`[BR-CAN-001]`)

Cancellation must always follow the **reverse downstream order**. Attempting to cancel an upstream document with active downstream documents is blocked with a `LinkValidationError`.

```
Correct Cancellation Sequence:

  Payment Entry  →  Sales Invoice  →  Delivery Note  →  Sales Order
  (cancel first)     (cancel 2nd)      (cancel 3rd)      (cancel last)
```

### Cancellation Rules

| Document | Blocked If | Result of Cancellation |
|----------|-----------|------------------------|
| **Sales Order** | Submitted DN or SI exists | — |
| **Delivery Note** | Submitted SI references it | Auto-cancels all linked Packing Slips; reverses stock |
| **Sales Invoice** | Linked Payment Entry exists | Reverses GL entries; resets DN `per_billed` % |
| **Payment Entry** | None | Reverses payment GL; restores SI outstanding amount |

### Step-by-Step Cancellation Example
1. Cancel the **Payment Entry** (if any) on the Sales Invoice.
2. Cancel the **Sales Invoice** — `per_billed` on DN reverts to 0%.
3. Cancel the **Delivery Note** — all packing slips auto-cancel; stock returns to warehouse.
4. Cancel the **Sales Order** (if required).

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| "Delivery Note is required" error on SI creation | Wholesale flow — no submitted DN | Create and submit a Delivery Note first |
| "Update Stock must be unchecked" error | Tried to create SI with `update_stock = 1` | Uncheck Update Stock on the Sales Invoice form |
| Cannot cancel Delivery Note | Sales Invoice still submitted | Cancel the SI first |
| Cannot cancel Sales Invoice | Payment Entry exists | Cancel the Payment Entry first |
| Multiple warehouse error on DN | Items from different warehouses | Use a single source warehouse per Delivery Note |
