# Core Customizations

Customizations, 3PL Logistics Workflows, and Dual Sales Architecture for Frappe / ERPNext.

---

## 1. Dual Sales & Fulfillment Architecture

The system supports two distinct sales and fulfillment flows designed for different operational channels:

```mermaid
graph TD
    subgraph Flow 1: Wholesale / 3PL Dispatch-First Flow
        SO[Sales Order] --> DN[Delivery Note<br><b>Stock Movement & Batch Allocation</b>]
        DN --> PS[Packing Slips 1..N<br><i>4x6 Carton Labels</i>]
        DN --> SI1[Sales Invoice<br><b>update_stock = 0</b><br><i>Requires Delivery Note</i>]
    end

    subgraph Flow 2: Retail / Over-the-Counter POS Flow
        POS[POS Register / Desk] --> PI[POS Invoice<br><b>Over-the-Counter Handover</b>]
        PI --> CE[POS Closing Entry<br><i>End-of-Day Shift Settlement</i>]
        CE --> SI2[Consolidated Sales Invoice<br><b>update_stock = 1</b><br><i>Exempted from Delivery Note</i>]
    end

    style SO fill:#f0f4f8,stroke:#3182ce,stroke-width:2px
    style DN fill:#e6fffa,stroke:#319795,stroke-width:2px
    style PS fill:#fefcbf,stroke:#d69e2e,stroke-width:2px
    style SI1 fill:#edf2f7,stroke:#718096,stroke-width:2px
    style POS fill:#feebc8,stroke:#dd6b20,stroke-width:2px
    style PI fill:#fed7d7,stroke:#e53e3e,stroke-width:2px
    style CE fill:#e9d8fd,stroke:#805ad5,stroke-width:2px
    style SI2 fill:#edf2f7,stroke:#718096,stroke-width:2px
```

---

## 2. Sales Returns & Credit Notes Lifecycle

Sales returns are handled specifically for each channel to preserve stock accuracy and tax compliance:

### A. Wholesale / B2B Return Flow (`SO` $\rightarrow$ `DN` $\rightarrow$ `SI`)
* **Physical Stock Return (Warehouse)**:
  * A **Delivery Note Return** is created against the original `Delivery Note` (`is_return: 1`, negative quantity).
  * Increases stock in the warehouse and restores batches.
* **Financial Credit Adjustment (Accounts)**:
  * A **Sales Invoice Return (Credit Note)** is generated against the original `Sales Invoice` (`is_return: 1`, `update_stock: 0`).
  * Reverses Accounts Receivable, revenue, and output GST.
  * **Validation Rule**: In `sales_invoice.py`, return invoices (`is_return: 1`) bypass the forward Delivery Note requirement.

### B. Retail / POS Return Flow (`POS` $\rightarrow$ `POS Invoice`)
* **Immediate Counter Refund**:
  * Cashier selects **"Return"** in the POS UI, creating a `POS Invoice` with negative quantities (`is_return: 1`).
  * Stock is immediately returned to the shelf/godown, and cash/card refund is issued to the customer.
* **Shift Settlement**:
  * The **POS Closing Entry** consolidates daily sales and returns into net revenue and consolidated Credit Note entries.

---

## 3. 3PL Logistics & Transporter Management

Logistics and transport settings are decoupled from billing and centralized into the **`Customer`** $\rightarrow$ **`Delivery Note`** $\rightarrow$ **`Packing Slip`** lifecycle.

### Customer Master Defaults
Configured under **Customer $\rightarrow$ Transporter & Shipping Settings**:
* **Default Transporter**: Linked `Supplier` (filtered with `is_transporter: 1`).
* **Origin / Booking Hub Address**: Dynamic booking office address (e.g. Parrys Booking Hub).
* **Is Godown Delivery**: Toggle for Transporter Godown pickup vs Door Delivery.
* **Destination Godown Address**: Customer's designated collection godown.

### Delivery Note Logistics Actions
* **`Logistics >> Transporter`**: Interactive modal to view or update Transporter, Origin Hub, and Destination Godown with live HTML address preview cards.
* **`Logistics >> Update LR Details`**: Modal requiring an active linked `Sales Invoice`:
  * Captures **LR / Consignment No** (`lr_no`) and **LR Date** (`lr_date`).
  * Captures **Line-Haul Vehicle / Truck No** (`vehicle_no`), **Mode of Transport**, and **GST Vehicle Type**.
  * Captures physical **LR Receipt Photo / Scan** (`custom_lr_receipt_image`), stored securely in Amazon S3 via `dfp_external_storage`.
  * Evaluates the **Sales Invoice Grand Total** against the ₹50,000 statutory E-Way Bill threshold.
  * If an active E-Way Bill exists and a vehicle number is entered, automatically synchronizes **Part B on the GST Portal via India Compliance**.
  * Synchronizes all transport fields and receipt images across both `Delivery Note` and `Sales Invoice`.
* **Automatic Contact & Shipping Details Fallback**:
  * Automatically populates `shipping_contact_person`, `shipping_contact_display`, `shipping_contact_mobile`, and `shipping_contact_email` from the customer's primary contact or linked billing contact whenever a Delivery Note is created or customer changed.



---

## 4. Indian GST E-Way Bill Compliance in 3PL Logistics

Under **Rule 138 & Rule 138A of the CGST Rules, 2017**, multi-leg transport involving local feeder transit (e.g. Auto Rickshaw / Tata Ace from 3PL Godown to Transporter Booking Hub) followed by long-haul truck movement is handled through a **single compliant workflow**:

```mermaid
graph LR
    subgraph Leg1 ["Leg 1: Local Feeder (≤ 50 km)"]
        Godown["3PL Godown<br/>(Dispatch From)"] -->|Auto Service / Feeder<br/>Part A Active<br/>Part B Exempt| Hub["Transporter Hub<br/>(Parrys / Koyambedu)"]
    end
    subgraph Leg2 ["Leg 2: Line-Haul Highway"]
        Hub -->|Heavy Truck / Lorry<br/>Transporter updates Part B<br/>with Truck Reg No & LR| Dest["Consignee / Destination Godown<br/>(Ship To)"]
    end
```

### Statutory Rules & Best Practices:

1. **Single E-Way Bill Principle**:
   * Under GST, **do NOT** raise two separate E-Way Bills (one for Delivery Note and another for Invoice) for the same commercial shipment.
   * A single E-Way Bill is generated against the **`Sales Invoice`** (Document Type: `Tax Invoice`) covering the complete transit from origin (3PL Godown) to destination (Consignee).

2. **The "Auto Service" First-Mile Exemption (Rule 138(3) Third Proviso)**:
   * When goods are moved from the consignor's godown to the transporter's hub/office within the same state for a distance of **up to 50 km**:
     * **Part A is Mandatory**: Generated with Invoice No, HSN, Taxable Value, Dispatch From Pincode, and **Transporter GSTIN / TRANSIN ID**.
     * **Part B (Vehicle Number) is EXEMPT**: Part B is left blank for the local auto leg.
     * **Zero Penalty Protection**: Carrying the E-Way Bill printout (showing Part A and Transporter Name) + Tax Invoice + Delivery Note is 100% legally compliant for GST road inspection within 50 km.

3. **Line-Haul Lorry Dispatch (Transporter Responsibility)**:
   * When the transporter receives the boxes at their booking hub, they assign the line-haul vehicle.
   * The transporter uses their Transporter ID on the EWB portal to update **Part B (Vehicle Number & LR No)** or generate a **Consolidated E-Way Bill (EWB-02)** before the truck departs on the highway.

### Transporter Part B Failure & Consignor Safeguards

What if the Transporter does not update Part B before the truck departs on the highway?

* **The Statutory Risk (CGST Section 129)**: Travelling on the highway beyond 50 km with Part B blank renders the E-Way Bill incomplete, attracting interception and tax penalties.
* **Consignor's Legal Authority (CGST Rule 138(5))**: Under GST law, **both the Consignor (Supplier) AND the Transporter** have equal legal authority to update Part B. You do not depend exclusively on the transporter.

#### Consignor Safeguard SOP:
```mermaid
graph TD
    A["Auto delivers boxes to Transporter Hub"] --> B["Transporter issues LR with Truck No"]
    B --> C{"Did Transporter update Part B?"}
    C -->|YES| D["Truck departs with E-Way Bill updated by Transporter"]
    C -->|NO / Small Transporter| E["3PL / Dispatcher enters Truck No & LR into ERPNext<br/>Clicks 'Update Part B' before highway departure"]
```

1. **Consignor Updates Part B upon Receiving LR (Recommended Standard)**:
   * Once the auto delivers boxes at the booking office, the transporter issues the **Lorry Receipt (LR)** containing the Line-Haul Truck Registration Number (e.g. `TN-28-AB-5678`).
   * The driver/staff shares the LR copy.
   * Your dispatch team enters the LR & Truck No in ERPNext / `india_compliance` (or EWB portal) and clicks **`Update Part B`**.
2. **Pre-assign Auto Vehicle Number at 3PL Dispatch (Zero-Risk First Mile)**:
   * Enter the Auto Registration Number (e.g. `TN-01-AZ-1234`) directly into Part B at 3PL dispatch. The E-Way Bill is immediately 100% active with both Part A and Part B.
   * Update the vehicle details to the lorry registration number once the LR is generated.

4. **Address Configuration on E-Way Bill**:
   * **Bill From**: Company Registered Billing Address & GSTIN.
   * **Dispatch From**: **3PL Godown Address & Pincode** (ensures distance calculation originates from the physical warehouse).
   * **Bill To**: Customer's Billing Address & GSTIN.
   * **Ship To**: Customer's Delivery / Destination Godown Address.

5. **3PL Dispatcher & Auto Driver Checklist**:
   * [ ] **Physical Boxes**: 4x6" Carton Shipping Labels pasted on each box (`Box [X] of [Y]`).
   * [ ] **Delivery Note**: Signed Delivery Note copy for transporter acknowledgement.
   * [ ] **GST Tax Invoice**: Accompanies the shipment.
   * [ ] **E-Way Bill Slip**: Generated with 3PL dispatch pincode and Transporter GSTIN.


---

## 5. Single Warehouse Confinement on Delivery Note

A Delivery Note is strictly confined to dispatching from a **single warehouse**:
* **Client-Side Trigger**: When editing the `warehouse` on any item row, if another warehouse is already set by earlier items, the form alerts the dispatcher and automatically reverts the row to the primary warehouse.
* **Server-Side Validation**: `validate_delivery_note` in `delivery_note.py` verifies all item rows belong to the same warehouse before save/submission.

---

## 6. Packing Slips & Carton Management

Accessible via the **`Packing Slips`** dropdown on `Delivery Note`:
* **`Generate`**: Generates single-item or mixed-item cartons with automatic `dn_detail` linkage, saved as Draft (`docstatus: 0`).
* **`Manage / Edit`**: Opens a consolidated, centralized modal table to view and perform actions on all carton boxes:
  * **Individual Status Indicators**: View `Draft`, `Submitted`, or `Cancelled` tags for each box.
  * **Inline Printing**: Print individual 4x6 thermal labels directly from the row. (Note: Printing is disabled for `Draft` slips to prevent accidental dispatch of unsubmitted boxes).
  * **Individual Actions**: Submit, Cancel, or Delete individual packing slips.
  * **Bulk Actions (Footer)**: 
    * `Submit All Draft Slips`: One-click submission of all draft packing slips.
    * `Delete All Packing Slips`: Non-interrupting partial deletion that safely deletes all `Draft` and `Cancelled` records while gracefully skipping any `Submitted` slips.
    * `Print All Slips`: Generates a continuous multi-page thermal print stream of all carton labels. Explicitly skips any unsubmitted `Draft` slips.

---

## 7. Document Cancellation & Dependency Guardrails

Strict relational dependency validation is enforced across the entire order fulfillment lifecycle:

```mermaid
graph RL
    SI["Sales Invoice (SI)<br/>(Accounts/Tax)"] -->|Must Cancel First| DN["Delivery Note (DN)<br/>(Stock/Dispatch)"]
    DN -->|Must Cancel Before| SO["Sales Order (SO)<br/>(Booking)"]
```

### Dependency Cancellation Rules:
1. **Sales Order Cancellation (`SO`)**:
   * **Blocked** if any submitted `Delivery Note` or `Sales Invoice` is linked.
   * Attempting to cancel an SO with an active downstream document throws `LinkValidationError`.
2. **Delivery Note Cancellation (`DN`)**:
   * **Blocked** if an active submitted `Sales Invoice` references it (`Sales Invoice Item.delivery_note`).
   * Once downstream Sales Invoices are cancelled, cancelling the `Delivery Note`:
     * Auto-cancels all submitted `Packing Slip` records attached to it (via `on_cancel_delivery_note` hook).
     * Reverses Stock Ledger and Batch ledger movements.
     * Restores Sales Order's `per_delivered` % to un-delivered status.
3. **Sales Invoice Cancellation (`SI`)**:
   * **Blocked** if linked `Payment Entry` exists.
   * Cancelling the SI reverses GL accounting entries and resets the Delivery Note's `per_billed` % without cancelling the Delivery Note.
4. **Strict Reverse Cancellation Sequence**:
   $$\text{Payment Entry} \longrightarrow \text{Sales Invoice (SI)} \longrightarrow \text{Delivery Note (DN)} \longrightarrow \text{Sales Order (SO)}$$


---

## 8. Print Formats Suite

### A. Delivery Note Print Formats (A4)
Available in 3 copies (`Original for Consignee`, `Duplicate for Transporter`, `Triplicate for Supplier`):
* **3-Column Header Architecture**:
  * **Consignor (Dispatch From)**: Renders the dispatch Warehouse title, Warehouse street address, and phone number (falling back to Company Dispatch/Shipping address).
  * **Consignee (Customer)**: Renders the Customer's **Shipping Address** (`shipping_address` / `shipping_address_name`) and shipping GSTIN (falling back to billing address if no separate shipping destination).
  * **Delivery & Logistics**: Clean breakdown of Transporter name, Booking Origin Hub, Godown Delivery destination vs Door Delivery mode, LR details, Vehicle No, and Total Box count.
* **Allocated Boxes Column**:
  * Displays Box No, Quantity, and exact **Packing Slip ID** against each item (e.g. `Box #1 (4000 Nos) • MAT-PAC-2026-00358`).
  * Dedicated consolidated table for mixed item cartons.
* **No Financial Clutter**: Rates and values are omitted to focus purely on goods receipt.
* **Dual Stamp & Signature Blocks**: Receiver's Acknowledgement (Left) and Company Authorised Signatory (Right).

### B. Confidential Carton Shipping Label (4" x 6")
* **DocType**: `Packing Slip` (`Carton Shipping Label (4x6)`).
* **Anti-Pilferage Security**: Commercial product names and quantities are omitted from outer labels to protect high-value goods in 3PL transit.
* **Prominent Logistics Info**: Large `BOX [ 1 ] OF [ 5 ]` counter, Consignee Destination, Transporter Booking Hub / Godown Pickup banner, and blank routing stamp box.

### C. GST Sales Invoice Print Formats (A4)
Available in 3 copies (`Original for Receiver`, `Duplicate for Transporter`, `Triplicate for Supplier`):
* **3-Column Header Architecture**:
  * **Bill To**: Renders Customer's **Billing Address** (`address_display` / `customer_address`) and billing GSTIN.
  * **Invoice Details**: Invoice No, Date, Time, Payment Due Date, Outstanding invoices summary, and **Sales Channel: Point of Sale (POS)** (if applicable).
  * **Payment & Status**: Bank NEFT/RTGS details, dynamic UPI QR code for unpaid invoices, or green `✓ Fully Paid` badge.
* **Dual Flow Awareness in Logistics Box**:
  * **Wholesale Flow**: Displays Transporter name, Booking Origin Hub, and Godown Destination / Door Delivery.
  * **POS Flow (`is_pos: 1` / `is_consolidated: 1`)**: Replaces 3PL logistics with:
    > **Delivery Mode:** Over-the-Counter / Point of Sale (POS)  
    > **POS Profile:** [POS Profile Name]  
    > *(Consolidated POS Shift Settlement)*
* **GST Breakup Table**: Tax rate, taxable amount, and GST split.


---

## 9. Running Automated Test Suites

Run integration tests for the entire app or by specific module:

```bash
# Run ALL 64 tests across the entire app
bench --site zap.localhost run-tests --app core_customizations

# Or run individual test modules:
# 1. Delivery Note 3PL Logistics & Single Warehouse (22 tests)
bench --site zap.localhost run-tests --module core_customizations.tests.test_delivery_note_workflow

# 2. Dual Sales Architecture (Wholesale + Retail POS + Returns + Cancellation) (7 tests)
bench --site zap.localhost run-tests --module core_customizations.tests.test_pos_dual_workflow

# 3. GST Sales Invoice Print Formats Suite (10 tests)
bench --site zap.localhost run-tests --module core_customizations.tests.test_gst_invoice_print_formats

# 4. Delivery Note Print Formats Suite (with Packing Slip IDs & Shipping Address) (11 tests)
bench --site zap.localhost run-tests --module core_customizations.tests.test_delivery_note_print_format

# 5. Thermal & 4x6 Carton Shipping Labels (4 tests)
bench --site zap.localhost run-tests --module core_customizations.tests.test_pos_label_print_formats

# 6. Monkey Patches & Packing Slip Overrides (4 tests)
bench --site zap.localhost run-tests --module core_customizations.tests.test_monkey_patches

# 7. Setup & Role Permissions Provisioning (4 tests)
bench --site zap.localhost run-tests --module core_customizations.tests.test_setup_permissions

# 8. Sales Invoice Custom Fields (2 tests)
bench --site zap.localhost run-tests --module core_customizations.tests.test_sales_invoice_customizations

### Cypress Frontend UI Tests
The app includes Cypress UI tests to validate frontend modals and workflow transitions:

```bash
# Run all Cypress UI tests headlessly
bench --site zap.localhost run-ui-tests core_customizations --headless

# Or open Cypress GUI to run tests interactively (requires X11/Desktop environment)
bench --site zap.localhost run-ui-tests core_customizations
```


---

## 10. Installation & Migration

To synchronize all customizations, custom fields, property setters, client scripts, and print formats:

```bash
bench --site zap.localhost migrate
```



