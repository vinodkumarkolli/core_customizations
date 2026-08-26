# Manual 06 — Role-Based Permissions & Access Control

**Files**: `after_migrate.py`, `setup_permissions.py`

---

## Overview

This app automatically provisions and enforces a custom permission structure for two key roles on every `bench migrate`. The permissions are applied programmatically — you do not need to manually set DocPerms in the UI.

---

## Roles Managed

### 1. `Employee Self Service`

This role is given **read-only** access to a carefully curated set of master data documents so employees can view necessary information without being able to modify financial or operational records.

**Permissions Granted** (Read = 1, Write = 0):

| DocType | Purpose |
|---------|---------|
| `Workflow State` | View document states in workflows |
| `Workflow` | View workflow definitions |
| `Workflow Action Master` | View workflow actions |
| `Project` | View project assignments |
| `Mode of Payment` | View payment mode options |
| `Employee` | View colleague profiles |
| `Supplier` | View supplier master (for reference) |
| `Item Price` | View current pricing |
| `Item Tax Template` | View tax template details |

### 2. `System Manager`

Given **read** access to `Employee` records (in addition to their existing administrative permissions).

---

## How Permissions Are Applied

Permissions are provisioned by `after_migrate.py` which calls `setup_permissions()`:

1. **Checks for existing Custom DocPerms**: If a `Custom DocPerm` already exists for the role on that DocType, it is skipped (idempotent).
2. **Copies the Standard DocPerm as baseline**: The standard permission entry is cloned and marked as `custom = 1`.
3. **Sets Read = 1** for the configured permissions.
4. **Logs all changes** to Frappe's standard logging system.

This runs automatically on every `bench migrate` — no manual configuration required.

---

## Verifying Permissions

### Via UI
1. Go to **Settings → Role Permissions Manager**.
2. Select `Document Type` (e.g. `Supplier`).
3. Check that `Employee Self Service` has `Read = 1` in the permissions table.

### Via Tests
```bash
bench --site zap.localhost run-tests --module core_customizations.tests.test_setup_permissions
```

Expected output:
```
✔  test_01_after_migrate_creates_custom_docperms
✔  test_02_standard_docperm_copied_when_custom_docperm_created
✔  test_03_obsolete_print_formats_cleaned_up
✔  test_04_core_customizations_print_formats_synced
```

---

## Modifying Permissions

To add a new permission (e.g. grant `Employee Self Service` access to `Purchase Order`):

1. Open [`after_migrate.py`](../core_customizations/after_migrate.py).
2. Find the `ROLE_PERMISSIONS` dictionary.
3. Add the new DocType to the `Employee Self Service` list.
4. Run `bench migrate` to apply.
5. Run tests to verify.

> ⚠️ **Do NOT** modify permissions directly via **Role Permissions Manager** in the UI for roles managed by this app. Those changes will be overwritten on the next `bench migrate`.

---

## Print Format Sync

In addition to permissions, `after_migrate.py` also:

### Syncs Required Print Formats
Ensures all required print formats are installed from fixtures. If a format is missing, it is re-synced from the fixture file. Required formats:

- `Delivery Note - Original for Consignee`
- `Delivery Note - Duplicate for Transporter`
- `Delivery Note - Triplicate for Supplier`
- `GST Invoice - Original for Receiver`
- `GST Invoice - Duplicate for Transporter`
- `GST Invoice - Triplicate for Supplier`
- `GST Purchase Order`
- `Carton Shipping Label (4x6)`
- `Shipping Package Label (4x6)`

### Cleans Up Obsolete Print Formats
Deletes stale/renamed print formats that should no longer exist (defined in the `OBSOLETE_PRINT_FORMATS` list in `after_migrate.py`). Currently cleans up:
- `Customer Delivery Address Label` (replaced by `Carton Shipping Label (4x6)`)

---

## Adding a New Role or DocType to Permissions

1. Edit [`after_migrate.py`](../core_customizations/after_migrate.py):

```python
ROLE_PERMISSIONS = {
    "Employee Self Service": [
        "Workflow State",
        "Supplier",
        # Add new DocType here:
        "Purchase Order",
    ],
}
```

2. Run migration:
```bash
bench --site zap.localhost migrate
```

3. Verify in UI: **Settings → Role Permissions Manager → Purchase Order** — `Employee Self Service` should have `Read = 1`.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Employee Self Service cannot see Supplier list | Permissions not synced after migration | Run `bench migrate` or manually run `after_migrate()` via `bench execute` |
| Print format missing after deployment | Fixture not exported before push | Run `bench export-fixtures --app core_customizations` and commit |
| Custom DocPerm overwritten on migrate | Someone manually edited permissions in UI | This is expected — `after_migrate.py` is the source of truth. Add the change to `setup_permissions.py` instead |
| Obsolete format not being deleted | Name mismatch in `OBSOLETE_PRINT_FORMATS` list | Check exact name in `bench --site ... list-docs "Print Format"` and update the list |
