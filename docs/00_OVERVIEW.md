# Core Customizations — Setup & User Manual Index

This directory contains step-by-step setup and operational manuals for every feature implemented in the `core_customizations` ERPNext application.

---

## Manuals

| # | Manual | Description |
|---|--------|-------------|
| 1 | [01_PROCUREMENT_AUTOMATION.md](./01_PROCUREMENT_AUTOMATION.md) | Auto Reorder → Material Request → Purchase Order automation |
| 2 | [02_3PL_LOGISTICS.md](./02_3PL_LOGISTICS.md) | 3PL transporter management, LR details, E-Way Bill, packing slips |
| 3 | [03_DUAL_SALES_ARCHITECTURE.md](./03_DUAL_SALES_ARCHITECTURE.md) | Wholesale Dispatch-First flow vs Retail POS Counter flow |
| 4 | [04_POINT_OF_SALE.md](./04_POINT_OF_SALE.md) | POS setup, counter flow, shift closing, and consolidated invoices |
| 5 | [05_PRINT_FORMATS.md](./05_PRINT_FORMATS.md) | GST Invoice, Delivery Note, Packing Slip, and PO print format setup |
| 6 | [06_PERMISSIONS_AND_ROLES.md](./06_PERMISSIONS_AND_ROLES.md) | Role-based access control and custom DocPerm setup |

---

## Quick Reference: Business Rules

All features map back to the [Business Blueprint](.agents/rules/business_blueprint.md).
Every code change must carry an inline `# @businessRule [BR-XXX]` tag referencing the applicable rule.
