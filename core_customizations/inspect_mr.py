import frappe
from frappe.model.meta import get_meta
import inspect
from erpnext.buying.doctype.material_request.material_request import make_purchase_order

def execute():
    meta = get_meta("Material Request Item")
    for df in meta.fields:
        if "supplier" in df.fieldname.lower():
            print(f"Material Request Item field: {df.fieldname}")
            
    print("make_purchase_order signature:", inspect.signature(make_purchase_order))
