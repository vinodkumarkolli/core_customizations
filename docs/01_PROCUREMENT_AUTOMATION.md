# Manual 01 — Automated Procurement: Auto Reorder → MR → Purchase Order

**Business Rules**: `[BR-PROC-001]` through `[BR-PROC-006]`  
**Files**: `core_customizations/material_request.py`, `hooks.py`

---

## Overview

When stock falls below the reorder level, ERPNext raises a **Material Request** of type `Purchase`. This app intercepts the MR submission and automatically generates a **Draft Purchase Order**, sends email notifications, and carries over the target warehouse — eliminating manual PO creation for routine replenishments.

```
Auto Reorder Trigger
        ↓
Material Request (type: Purchase) — Submitted
        ↓  [on_submit hook]
  Single supplier per item? ──NO──→ Abort + Log Error (Manual PO)
        │ YES
        ↓
  Draft Purchase Order created
  (set_warehouse carried over)
        ↓
  Email → Supplier + Internal Team
```

---

## Prerequisites

### 1. Configure Item Reorder Levels
1. Open the **Item** master.
2. Go to the **Inventory** tab → **Auto Reorder** table.
3. For each warehouse that should trigger reorders, add a row:

   | Field | Value |
   |-------|-------|
   | **Warehouse** | e.g. `Stores - SE-K` (the warehouse to monitor) |
   | **Check Availability In Warehouse** | Same warehouse as above |
   | **Reorder Level** | e.g. `10000` (trigger when stock falls below this) |
   | **Reorder Qty** | e.g. `25000` (how many to order) |
   | **Material Request Type** | **`Purchase`** ← Select this from the dropdown. This is the trigger that feeds our automation. When the scheduler fires, it creates a MR of type `Purchase`, which our `auto_create_po` hook then converts into a Draft PO automatically. |

### 2. Configure Exactly One Supplier per Item ⚠️
> **Critical — `[BR-PROC-003]`**: The automation fires **only** when an item has **exactly 1 supplier** configured. Items with 0 or 2+ suppliers will cause the automation to abort for the entire MR.

1. Open the **Item** master → **Purchasing** tab.
2. Under **Supplier Details → Item Supplier** table, add **exactly one** row:

   | Field | Value |
   |-------|-------|
   | **Supplier** | e.g. `Kodanda Rama Ayurveda Nilayam` |
   | **Supplier Part Number** | *(optional)* |

3. Click **Save**.

### 3. Configure Supplier Email (via Contact)

> The email is fetched from the **Contact** linked to the Supplier — NOT from the Supplier document itself.

1. Go to **Buying → Supplier** → open your Supplier (e.g. `Kodanda Rama Ayurveda Nilayam`).
2. Click the **Contacts & Addresses** tab.
3. Click **New Contact** (or open an existing contact if already linked).
4. Fill in:

   | Field | Value |
   |-------|-------|
   | **First Name** | Contact person's name |
   | **Email ID** | `purchase@supplier.com` ← this is what gets emailed |

5. In the **Links** table at the bottom of the Contact form, verify the Supplier is linked:
   - **Link Document Type**: `Supplier`
   - **Link Name**: *(your supplier name)*
6. **Save** the Contact.

**Email fallback chain** (in order):
```
1. Supplier → linked Contact → email_id    ← configure here
2. Company → email field                   ← internal team (see step below)
3. System Manager user email               ← last resort
```

### 4. Configure Internal Purchasing Email (Company)

### 4. Configure Warehouse Address (for Print Format)
For the `GST Purchase Order` print format to display the correct delivery address in the *Ship To* column:
1. Go to **Stock → Warehouse** → open the target warehouse (e.g. `WIP Godown - Sravi`).
2. Click **Edit** and note the Warehouse name.
3. Go to **Contacts → Address** → click **New**.
4. Set **Address Type** to `Shipping`.
5. Fill in the full warehouse address (Street, City, Pin, State).
6. In the **Links** table at the bottom, add:
   - **Link Document Type**: `Warehouse`
   - **Link Name**: *(your warehouse name)*
7. **Save** the Address.

### 5. PDF Password Rule
The auto-generated PO PDF uses a password rule for supplier privacy.

1. If the supplier has a GSTIN in `Supplier.tax_id` or `Supplier.gstin`, use that value as the PDF password.
2. If both fields are empty, keep the PDF attached and use a fallback password from the supplier name.
3. Build the fallback password from the first 8 letters of the supplier name.
4. Remove spaces, symbols, and numbers before you count the letters.
5. If fewer than 8 letters remain, pad the password with digits in order until it reaches 8 characters.

Examples:

| Supplier name | Fallback password |
|---------------|-------------------|
| `S 1@u_pp!?` | `SUPP1234` |
| `SUPPL` | `SUPPL123` |
| `SUPPLI` | `SUPPLI12` |

---

## How It Works (Automatic)

Once the above is configured, the automation is fully transparent:

1. **Scheduler runs Auto Reorder** (daily, overnight): ERPNext checks all items across all warehouses and raises Material Requests where stock < Reorder Level.
2. **MR is auto-submitted** by the reorder job.
3. **`auto_create_po` hook fires** on MR submission:
   - Validates `material_request_type == "Purchase"`.
   - Checks idempotency (no duplicate PO for same MR).
   - Verifies exactly 1 supplier per item — aborts with error log if not.
   - Calls ERPNext's native `make_purchase_order` mapper.
   - Assigns `supplier` and `set_warehouse` from the MR.
   - Calls `set_missing_values()` to resolve taxes, addresses, etc.
   - Inserts the PO as **Draft**.
   - Dispatches email to Supplier contact + Company purchasing email.
4. **Purchasing team receives email** and reviews the Draft PO in ERPNext.
5. **Purchasing team submits the PO** after review.

---

## Manual Trigger (Testing)

To test the automation without waiting for the overnight scheduler:

1. Go to **Stock → Material Request → New**.
2. Set:
   - **Purpose**: `Purchase`
   - **Target Warehouse**: *(warehouse with configured reorder)*
   - Add an item that has exactly 1 supplier configured.
3. **Save** and **Submit**.
4. Within seconds, navigate to **Buying → Purchase Order** — a new Draft PO should appear.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| No PO created after MR submit | Item has 0 or 2+ suppliers | Check `Item → Purchasing → Item Supplier` table — ensure exactly 1 row |
| No PO created | MR type is not `Purchase` | Set `material_request_type = Purchase` on the MR |
| PO created but no email sent | Supplier has no Contact with email | Add Contact with email to the Supplier master |
| PO created with wrong address | Warehouse has no linked Address | Create an Address record linked to the Warehouse (see setup step 4) |
| Duplicate PO not prevented | Idempotency check failing | Check `[BR-PROC-006]`: verify `Purchase Order Item.material_request` field is set |

Check **Frappe Error Log** (Settings → Error Log) for detailed `MR→PO Automation Skipped` messages.

---

## Related Business Rules

- `[BR-PROC-001]` Supplier resolved from Item Supplier child table
- `[BR-PROC-002]` POs always remain Draft for human review
- `[BR-PROC-003]` Single-supplier constraint — automation aborts if != 1 supplier
- `[BR-PROC-004]` `set_warehouse` propagated from MR to PO
- `[BR-PROC-005]` Email to both Supplier and internal team on PO creation
- `[BR-PROC-006]` Idempotency — no duplicate PO for same MR
