# Manual 02 — 3PL Logistics & Transporter Management

**Business Rules**: `[BR-LOG-001]`, `[BR-LOG-002]`, `[BR-EWB-001]` through `[BR-EWB-003]`, `[BR-PAC-001]`, `[BR-PAC-002]`  
**Files**: `delivery_note.py`, `sales_invoice.py`, client scripts

---

## Overview

This app implements a complete 3PL (Third-Party Logistics) dispatch workflow on top of ERPNext's Delivery Note. It covers:
- Customer-level transporter defaults
- LR (Lorry Receipt) and vehicle number capture
- E-Way Bill Part B synchronization via India Compliance
- Packing slip (carton label) generation and lifecycle management

---

## Setup

### 1. Configure Customer Transporter Defaults

For each B2B/Wholesale Customer, configure their standard logistics settings so they auto-populate on every Delivery Note.

1. Open the **Customer** master.
2. Navigate to the **Transporter & Shipping Settings** tab (custom tab added by this app).
3. Fill in:

   | Field | Description |
   |-------|-------------|
   | **Default Transporter** | Link to a `Supplier` with `is_transporter = 1` (e.g. `DTDC`, `Tirupati Courier`) |
   | **Transporter Origin Hub Address** | The booking hub address (e.g. `Parrys Booking Hub`) |
   | **Is Godown Delivery** | Toggle ON if this customer collects from a Transporter Godown instead of door delivery |
   | **Destination Godown Address** | Customer's godown pickup address (only visible if Godown Delivery = Yes) |

4. **Save** the Customer.

### 2. Mark Suppliers as Transporters

For a Supplier to appear in the Transporter field:

1. Open the **Supplier** master → **More Info** tab.
2. Check the **Is Transporter** checkbox.
3. Ensure the Supplier has a valid **GSTIN** / **TRANSIN ID** for E-Way Bill compliance.

### 3. Configure Company Bank Details for Invoices

Company bank details appear in the payment column of GST Sales Invoice print formats:

1. Go to **Accounts → Company** → open your Company.
2. Scroll to **Bank Details for Printing** (custom child table).
3. Add rows:

   | Print Label | Print Value |
   |-------------|-------------|
   | `Bank Name` | `State Bank of India` |
   | `Account No` | `XXXXXXXXXX` |
   | `IFSC` | `SBIN0XXXXXX` |
   | `UPI ID` | `yourcompany@upi` ← generates QR code on unpaid invoices |

---

## Delivery Note Workflow

### Creating a Delivery Note

1. Go to **Stock → Delivery Note → New** (or create from a Sales Order).
2. Select the **Customer** — transporter defaults auto-populate from the Customer master (`[BR-LOG-001]`).
3. Add items and set the **Source Warehouse** (must be a single warehouse — `[BR-INV-001]`).

### Updating Transporter Details

From the Delivery Note, click **Logistics → Transporter** to open the transporter modal:
- View or override the **Transporter**, **Origin Hub**, and **Destination Godown**.
- Live HTML address preview cards update as you type.
- Click **Update** to save.

### Capturing LR Details (Post-Dispatch)

After the auto has delivered goods to the booking hub and the LR is received:

1. Ensure a **Sales Invoice** is linked to the Delivery Note (required).
2. Click **Logistics → Update LR Details**.
3. Fill in:

   | Field | Description |
   |-------|-------------|
   | **LR No** | Lorry Receipt / Consignment number from Transporter |
   | **LR Date** | Date of LR issue |
   | **Vehicle No** | Line-haul truck registration (e.g. `TN28AB5678`) |
   | **Mode of Transport** | `Road`, `Rail`, `Air`, or `Ship` |
   | **GST Vehicle Type** | `Regular` or `Over Dimensional Cargo` |
   | **LR Receipt Image** | Upload a photo/scan of the physical LR |

4. Click **Update LR Details**.
   - Fields sync to both the Delivery Note and linked Sales Invoice (`[BR-LOG-002]`).
   - If the Sales Invoice Grand Total ≥ ₹50,000 and an active E-Way Bill exists, **Part B is automatically updated** on the GST Portal via India Compliance.

---

## E-Way Bill Compliance (Rule 138)

### Single E-Way Bill Principle (`[BR-EWB-001]`)
Generate **one** E-Way Bill against the **Sales Invoice** (Tax Invoice) — not against the Delivery Note. This single EWB covers the full transit.

### First-Mile Auto Service Exemption (`[BR-EWB-002]`)
When goods move from your 3PL godown to the transporter's booking hub (≤ 50 km by auto/feeder):
- **Part A** is mandatory (fill Transporter GSTIN / TRANSIN, dispatch pincode).
- **Part B (Vehicle Number) is EXEMPT** for ≤ 50 km feeder leg.
- Carry: EWB printout + Tax Invoice + Delivery Note for road inspection.

### Updating Part B After LR (`[BR-EWB-003]`)
Once the line-haul truck is assigned by the transporter:
1. Enter Vehicle No and LR No via **Logistics → Update LR Details**.
2. The system auto-calls India Compliance's Part B update API if:
   - An active E-Way Bill exists on the Sales Invoice.
   - The invoice Grand Total ≥ ₹50,000.
   - A Vehicle No is provided.

---

## Packing Slips & Carton Management

### Generating Packing Slips (`[BR-PAC-001]`)

From the Delivery Note toolbar, click **Packing Slips → Generate**:

| Option | Use Case |
|--------|----------|
| **Single Item Cartons** | Each item gets its own dedicated carton box |
| **Mixed Item Carton** | Multiple items packed into one shared carton |

Generated slips are saved as **Draft** (`docstatus = 0`). Draft slips are excluded from the Delivery Note print format.

### Managing Packing Slips

Click **Packing Slips → Manage / Edit** to open the consolidated carton management modal:

| Column | Description |
|--------|-------------|
| **Box No** | Auto-generated `Box X of Y` counter |
| **Items** | Items and quantities in that carton |
| **Status** | `Draft` / `Submitted` / `Cancelled` badge |
| **Actions** | Submit, Cancel, Delete, Print individual slips |

**Bulk Actions (footer)**:
- **Submit All Draft Slips**: One-click submission of all Draft packing slips.
- **Delete All Packing Slips**: Deletes all Draft and Cancelled slips; skips Submitted.
- **Print All Slips**: Multi-page thermal print stream (skips unsubmitted Drafts).

### Automatic Lifecycle (`[BR-PAC-002]`)

| Delivery Note Event | Packing Slip Action |
|--------------------|---------------------|
| **DN Submitted** | All Draft packing slips are **auto-submitted** |
| **DN Cancelled** | All Submitted packing slips are **auto-cancelled** |

---

## Shipping Labels

Two thermal label formats are available under `Packing Slips → Print All Slips`:

### 4x6 Carton Shipping Label (`Carton Shipping Label (4x6)`)
- **DocType**: Packing Slip
- Prints `BOX [X] OF [Y]`, Consignee name & destination, Transporter/Routing section, blank stamp box.
- **Security**: Product names and quantities are intentionally **omitted** to prevent pilferage in 3PL transit.

### Shipping Package Label (`Shipping Package Label (4x6)`)
- Includes full logistics routing including Godown Pickup vs Door Delivery banner.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Transporter not auto-populating | Customer has no Transporter default | Set Default Transporter in Customer → Transporter & Shipping Settings |
| "Update LR Details" button missing | No submitted Sales Invoice linked | Create and submit a Sales Invoice against this Delivery Note first |
| Part B not updating automatically | EWB not active or amount < ₹50,000 | Check E-Way Bill status in India Compliance; verify Grand Total |
| Packing slips not submitted on DN submit | Slips are already Submitted | This is expected; already-submitted slips are skipped |
| Godown delivery address not rendering | `Is Godown Delivery` off or address not set | Toggle `Is Godown Delivery` on Customer and set `Destination Godown Address` |
