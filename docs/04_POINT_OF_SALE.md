# Manual 04 — Point of Sale (POS) Setup & Operations

**Business Rules**: `[BR-SALES-002]`, `[BR-RET-002]`  
**Files**: `sales_invoice.py`, POS Profile configuration

---

## Overview

The Retail / POS flow handles over-the-counter transactions. POS Invoices are created directly at the counter, stock and payment are captured immediately, and the end-of-day **POS Closing Entry** creates a consolidated Sales Invoice. This flow is completely exempt from the Delivery Note requirement.

```
POS Counter
    ↓
POS Invoice (per transaction)
  - Stock movement: immediate
  - Payment: captured (cash/card/UPI)
    ↓
POS Closing Entry (end of shift)
    ↓
Consolidated Sales Invoice
  - update_stock = 1
  - Exempt from Delivery Note requirement
```

---

## Setup

### 1. Create a POS Profile

1. Go to **Retail → POS Profile → New**.
2. Configure:

   | Field | Description |
   |-------|-------------|
   | **POS Profile Name** | e.g. `Counter Sales - Chennai` |
   | **Company** | Your company |
   | **Warehouse** | Source warehouse for stock deduction (e.g. `Showroom - Sravi`) |
   | **Currency** | `INR` |
   | **Write Off Account** | For rounding adjustments |
   | **Customer** | Default walk-in customer (e.g. `Walk-In Customer`) |
   | **Tax Category** | Default GST tax template |
   | **Print Format** | `GST Invoice - Original for Receiver` |

3. Under **Payment Methods**, add all accepted payment modes:
   - Cash
   - Card (Credit / Debit)
   - UPI / Paytm
   - Bank Transfer (for B2B counter sales)

4. Under **Applicable User**, add all cashiers/billing staff who can use this POS.

5. **Save** the POS Profile.

### 2. Create a Walk-In Customer (Optional but Recommended)

For retail counter sales where the customer is not registered:

1. Go to **Selling → Customer → New**.
2. Set:
   - **Customer Name**: `Walk-In Customer`
   - **Customer Group**: `Retail`
   - **Territory**: `All Territories`
3. **Save**.
4. Link this customer as the Default Customer in your POS Profile.

### 3. Configure GST Tax Template for POS

1. Go to **Accounts → Sales Taxes and Charges Template → New**.
2. Add your GST rows (CGST 9% + SGST 9%, or IGST 18%, etc.).
3. Set this template as the **Sales Taxes and Charges Template** in your POS Profile.

---

## Daily POS Operations

### Opening a POS Session

1. Go to **Retail → Point of Sale**.
2. Select your **POS Profile**.
3. Enter the **Opening Cash Balance**.
4. Click **Open** to start the shift session.

### Creating a POS Invoice (Per Transaction)

1. In the POS interface, scan items or search by item code/name.
2. Adjust quantities as needed.
3. Apply any discounts.
4. Select the **Payment Mode** (cash, card, UPI).
5. Enter the amount tendered (cash change is calculated automatically).
6. Click **Submit** — the POS Invoice is created, stock is deducted, payment is recorded.

### Printing the Invoice
- Click **Print** on the completed POS Invoice.
- Select **GST Invoice - Original for Receiver** for the standard GST copy.
- The print format shows POS-specific information:
  > **Sales Channel:** Point of Sale (POS)  
  > **POS Profile:** Counter Sales - Chennai

### Processing a Return / Refund

1. In the POS interface, click **Return** or go to the original POS Invoice.
2. Select the items and quantities to return.
3. A negative POS Invoice is created — stock is immediately returned to the warehouse.
4. Refund the customer via the same or alternate payment mode.

---

## End-of-Day Shift Closing

### Closing the POS Session

1. From the POS interface, click **Close POS** (top-right menu).
2. Count actual cash in the drawer and enter the **Closing Balance**.
3. The system shows:
   - **Expected Closing Balance** (opening + cash sales − cash refunds)
   - **Difference** (shortage or excess)
4. Enter any closing notes.
5. Click **Close**.

### What Happens on POS Close (`[BR-SALES-002]`)

The POS Closing Entry automatically:
1. Creates a single **Consolidated Sales Invoice** covering all POS Invoices in the session.
   - `update_stock = 1` (stock movement happens here)
   - Completely bypasses the Delivery Note requirement
   - `is_consolidated = 1` flag is set
2. Reconciles all payment entries (cash, card, UPI).
3. Posts GL entries for revenue, taxes, and cash collections.

> **Important**: The Consolidated Sales Invoice is system-generated and should **not** be manually edited.

---

## GST Invoice Print Format for POS

The GST Invoice print format automatically detects POS transactions via the `is_pos`, `is_consolidated`, and `pos_profile` fields:

- **Invoice Details column** shows: `Sales Channel: Point of Sale (POS)`
- **Shipping & Logistics column** shows:
  > **Delivery Mode:** Over-the-Counter / Point of Sale (POS)  
  > **POS Profile:** Counter Sales - Chennai  
  > *(Consolidated POS Shift Settlement)* — for consolidated invoices

---

## POS-Specific Validations Bypassed

| Validation | Standard (Wholesale) | POS |
|------------|---------------------|-----|
| Delivery Note required before SI | ✅ Required | ❌ Exempt |
| `update_stock = 0` on SI | ✅ Enforced | ❌ Exempt (update_stock = 1 allowed) |
| Credit note bypass | ✅ `is_return = 1` exempt | ✅ `is_return = 1` exempt |

---

## Multi-Register / Multi-Shift Setup

For businesses with multiple POS counters or shifts:

1. Create a separate **POS Profile** for each counter/shift:
   - `Counter Sales - Morning Shift`
   - `Counter Sales - Evening Shift`
   - `Showroom Counter - Branch 2`
2. Assign different **Applicable Users** to each profile.
3. Each POS Profile generates its own independent Closing Entry and Consolidated Invoice.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| "Delivery Note required" on POS Invoice | POS Invoice is not being detected as POS | Ensure `is_pos = 1` on the POS Invoice; use the POS interface, not manual SI creation |
| Stock not deducting on POS Invoice | `update_stock = 0` on POS Invoice | In POS Profile, verify warehouse is set; POS Invoices always have `update_stock = 1` |
| Consolidated Invoice not created | POS Closing Entry failed | Check Error Log; ensure all POS Invoices are submitted before closing |
| UPI QR not showing on invoice print | Invoice is fully paid | QR only appears when `outstanding_amount > 0`; it hides after payment is recorded |
| Wrong warehouse deducted | POS Profile warehouse not set | Set `Warehouse` in POS Profile → this is the default deduction warehouse for all POS items |
