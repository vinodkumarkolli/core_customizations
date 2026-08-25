import json

file_path = "core_customizations/fixtures/client_script.json"

with open(file_path, "r") as f:
    scripts = json.load(f)

for s in scripts:
    if s["dt"] == "Delivery Note" and "@functionalPurpose" not in s["script"]:
        jsdoc = """/**
 * @functionalPurpose Handles interactive logistics popups, transporter selection, and packing slip generation.
 * @businessPurpose Simplifies data entry for 3PL logistics dispatchers and enforces validation rules.
 * @businessRule [BR-LOG-001] Customer Transporter Defaults
 * @businessRule [BR-LOG-002] Sync LR Details
 */
"""
        # insert after the copyright header
        script_body = s["script"]
        if "// For license information" in script_body:
            parts = script_body.split("// For license information, please see license.txt\n\n", 1)
            if len(parts) == 2:
                s["script"] = parts[0] + "// For license information, please see license.txt\n\n" + jsdoc + parts[1]
        else:
            s["script"] = jsdoc + script_body

    elif s["dt"] == "Sales Invoice" and "@functionalPurpose" not in s["script"]:
        jsdoc = """/**
 * @functionalPurpose Displays outstanding amounts and overdue days as buttons on the invoice form.
 * @businessPurpose Reminds users of customer dues during invoice creation.
 */
"""
        s["script"] = jsdoc + s["script"]

    elif s["dt"] == "Purchase Invoice" and "@functionalPurpose" not in s["script"]:
        jsdoc = """/**
 * @functionalPurpose Validates supplier is a transporter and enforces cost center selection.
 * @businessPurpose Ensures freight accounting is properly recorded.
 */
"""
        s["script"] = jsdoc + s["script"]
        
    elif s["dt"] == "Payment Entry" and "@functionalPurpose" not in s["script"]:
        jsdoc = """/**
 * @functionalPurpose Displays outstanding amounts and validates correct bank accounts for mode of payment.
 * @businessPurpose Ensures payments are credited to the correct corporate accounts.
 */
"""
        s["script"] = jsdoc + s["script"]

with open(file_path, "w") as f:
    json.dump(scripts, f, indent=1)

print("Updated client_script.json successfully.")
