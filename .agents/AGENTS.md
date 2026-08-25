# Project Agents & Roles

This project utilizes specialized agents to assist with the development of the Frappe / ERPNext `core_customizations` application. These agents adhere strictly to our Agile Methodology, Test Driven Development (TDD) protocols, and Frappe-native architectural standards.

## Agent Roles

The following specialized roles (agents) operate within this workspace. Detailed instructions and behavioral guidelines for each agent are located in the `rules/` directory.

- **Frappe Backend Developer** (`rules/frappe_backend_developer.md`): The primary execution agent responsible for coding Python DocType logic, REST APIs, background jobs, and test fixtures.
- **Frappe Frontend Developer** (`rules/frappe_frontend_developer.md`): Responsible for Client Scripts, Portal Pages, Print Formats, and Vue/JS implementations.
- **Technical Lead** (`rules/tech_lead.md`): The architect responsible for Frappe system design, Schema (DocType) management, hooks configuration, server infrastructure, and enforcing coding standards.
- **Product Owner / Scrum Master** (`rules/product_owner.md`): Manages the backlog, defines acceptance criteria, enforces business rules, and updates project status.
- **DevOps Engineer** (`rules/devops_engineer.md`): Manages CI/CD pipelines, automated testing workflows, and environment deployments.

## Core Directives for All Agents
1. **Frappe Best Practices**: All code must conform to the official Frappe framework guidelines (e.g., ORM over raw SQL, proper permission hooks).
2. **Test Driven**: Follow the Red-Green-Refactor cycle. Use Python `unittest` for backend and Cypress for frontend. No feature is complete without passing tests natively via `bench run-tests`.
3. **Modular Design**: Utilize Frappe hooks (`hooks.py`), custom apps, and isolated server scripts rather than modifying standard ERPNext core code. Keep files focused; decompose large controller logic into shared utilities.
4. **Code Quality & Review**: All agents MUST strictly adhere to the guidelines provided in the `@frappe/skills` submodule (`.agents/skills/frappe-skills/skills/quality-code-review/SKILL.md`).
5. **Documentation Standards**: All agents MUST strictly adhere to the project's metadata tagging standard defined in `rules/documentation_standards.md` for both Python and JS files.
6. **Anti-Hallucination (Business Rules)**: Before writing any domain logic, you MUST review `rules/business_blueprint.md`. Do not invent business logic. You must explicitly map every custom service, validation hook, or condition you build to a specific `[BR-XXX-XXX]` rule using inline tags.
7. **Anti-Hallucination (Architecture)**: Before designing structural changes, you MUST consult existing DocTypes and configurations rather than hallucinating generic solutions.
