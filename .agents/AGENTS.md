# AI Agent Operating Guidelines

You are an AI Agent assisting with the development of `core_customizations`, a Frappe Framework application. When developing features, fixing bugs, or refactoring code in this repository, you MUST strictly adhere to the following workflow and standards.

## 1. Test-Driven Development (TDD)
- **Tests First**: Before writing any implementation code (Python, JavaScript, or Frappe DocType configurations), you must write the failing test cases.
- **Backend Tests**: Place all Python unit and integration tests in the `tests/` directory using the standard Frappe test runner (`unittest`).
- **Frontend Tests**: Place all Cypress UI tests in the `cypress/integration/` directory. If your UI tests require specific background data, you must write a self-contained Python helper script (e.g. `test_ui_helpers.py`) and use `frappe.xcall` to provision the test data securely.
- **Commit to Green**: Ensure all newly written tests pass natively in the backend before concluding your task.

## 2. AGILE Workflow
- **Iterative Execution**: Break down large architectural requests into small, incremental chunks. Do not attempt monolithic code refactors in a single pass.
- **Continuous Verification**: After every significant file edit, run the specific test file that covers that change to verify it. Do not wait until the end of a long execution chain to run tests.
- **CI/CD Awareness**: Our repository relies on a self-hosted GitHub Actions CI runner (`msi-fedora-docker`) running Frappe Version 16. Ensure your changes will survive the automated CI pipeline.

## 3. Code Annotation & Documentation
- **Docstrings**: All Python functions and classes MUST have clear, descriptive docstrings explaining their exact purpose, arguments, and return types.
- **In-line Comments**: Add in-line comments for complex logic, especially when interacting with Frappe's ORM (`frappe.get_doc`, `frappe.db.sql`, etc.) or specific domain business rules.
- **Why over What**: Your comments should explain *why* a technical or architectural decision was made (e.g. "We disable update_stock for 3PL items here to force them through the PR pipeline"), rather than just reciting what the code literally does.
- **Maintain Best Practices**: Keep our documentation files up to date. If your code changes architectural paradigms or DevOps infrastructure, update `BEST_PRACTICES_3PL.md` and `DEVOPS.md` respectively.

## 4. Frappe Specific Standards
- **ORM over SQL**: Never write direct SQL queries (`frappe.db.sql`) when standard ORM methods (`frappe.get_list`, `frappe.get_all`, or `frappe.get_doc`) can accomplish the task efficiently.
- **Permissions**: Do not bypass permissions (`ignore_permissions=True`) in production code unless absolutely necessary (it is acceptable for test data setup).
- **Version Awareness**: Keep in mind that this app runs on Frappe Version 16, which utilizes modern standards like `pyproject.toml` instead of `setup.py` and targets Node.js 24.x LTS.
