# Documentation & Metadata Tagging Standards

To ensure accountability, prevent agent hallucination, and maintain a single-source-of-truth audit trail directly within the code, all agents **MUST** strictly adhere to the following metadata tagging standard. 

These tags ensure that the *why* (Business Rules from `.agents/rules/business_blueprint.md`) is always coupled with the *how* (Implementation).

## 1. Python Backend Standards (Google-Style Docstrings)
All Python functions, classes, and hooks must use Google-style docstrings enriched with our custom metadata tags.

### Standard Tags
* `Business Purpose:` Explains the underlying operational or business goal, referencing a specific Epic.
* `Args:` Standard Google-style description of parameters.
* `Returns:` Standard Google-style description of return objects.
* `Raises:` Explicit list of exceptions thrown.

### Inline Logic & Formula Annotation Tags
Inline comments placed directly at point-of-use inside complex Python function bodies.
* `@businessRule [BR-XXX-XXX]`: Mandatory inline comment on major conditional branches explaining why domain boundaries are enforced.
* `@businessFormula`: Mandatory inline comment on complex variable initializations or math.

### Example: Python Controller / Utility
```python
def validate_delivery_note_on_sales_invoice(doc, method):
    """
    Validates that a Sales Invoice has an attached Delivery Note if it belongs to the wholesale flow.
    
    Business Purpose: Enforces the dispatch-first flow (Epic 1) to ensure wholesale orders are fully packed before billing.
    
    Args:
        doc (Document): The Sales Invoice document being validated.
        method (str): The hook method name (e.g., 'validate').
        
    Raises:
        frappe.ValidationError: If the required Delivery Note is missing.
    """
    if doc.is_pos or doc.is_return:
        return
        
    # @businessRule [BR-SALES-001] Wholesale Dispatch-First Flow
    # Sales Invoices must not be created without a prior Delivery Note unless it's a POS transaction.
    if not doc.get("items")[0].get("delivery_note"):
        frappe.throw("Wholesale Sales Invoices require an active Delivery Note.")
```

## 2. JavaScript / Frontend Standards (JSDoc)
All Frappe Client Scripts (whether physical `.js` files or embedded in JSON fixtures) must use JSDoc metadata tags.

* `@functionalPurpose`: High-level technical description of what the JS function executes.
* `@businessPurpose`: Explains the underlying operational or business goal.
* `@businessRule [BR-XXX-XXX]`: Mandatory inline JS comment for domain logic.

### Example: Client Script (embedded or .js)
```javascript
/**
 * @functionalPurpose Filters the Transporter field based on Customer defaults.
 * @businessPurpose Simplifies data entry for 3PL logistics dispatchers.
 */
frappe.ui.form.on('Delivery Note', {
    refresh: function(frm) {
        // @businessRule [BR-LOG-001] Customer Transporter Defaults
        if (frm.doc.customer && !frm.doc.transporter) {
            frappe.call({
                method: "get_customer_transporter",
                args: { customer: frm.doc.customer },
                callback: function(r) {
                    if (r.message) {
                        frm.set_value("transporter", r.message);
                    }
                }
            });
        }
    }
});
```

## 3. JSON Fixtures Registry
Frappe Custom Fields, Property Setters, and structural fixtures are exported as pure JSON (`.json`) files which **do not support comments**.

### Strategy
1. **Script Fixtures (`Client Script`, `Server Script`)**: Inject the standard JSDoc/Python comments containing the `@businessRule` tags directly inside the `script` string field of the JSON.
2. **Structural Fixtures (`Custom Field`, etc.)**: All structural JSON modifications must be logged in `docs/FIXTURES_REGISTRY.md`. You must document which `[BR-XXX]` rule prompted the schema change, the affected DocType, and a brief rationale.

### Example Registry Entry (in docs/FIXTURES_REGISTRY.md)
* **Date**: 2026-08-25
* **Target**: `Custom Field: Delivery Note-transporter_name`
* **Business Rule**: `[BR-LOG-001]`
* **Rationale**: Added a custom link field to Supplier (is_transporter=1) to support 3PL tracking.
