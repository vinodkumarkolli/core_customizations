---
name: tech-lead-review
description: >-
  Use this skill to perform a Tech Lead review of the codebase.
  Triggers the Tech Lead persona to audit architecture, performance, and code quality.
---

# Tech Lead Review Skill

When invoked, the agent assumes the role of the Technical Lead and performs the following checks:

1. **Modularity Audit**: Check if any single Python controller is becoming monolithic (e.g., exceeding 300-400 lines). Suggest decomposing logic into `utils.py` or domain-specific helpers.
2. **Performance Audit**: Look for Frappe ORM anti-patterns, such as `db.get_value` inside for-loops, missing indexes, or raw SQL (`frappe.db.sql`) with string concatenation.
3. **Quality Code Review**: Cross-reference the latest changes with the `@frappe/skills` quality checklist (`.agents/skills/frappe-skills/skills/quality-code-review/SKILL.md`).
4. **Actionable Feedback**: Provide a structured markdown response with clear "Blockers" (issues that must be fixed before merging) and "Suggestions" (architectural improvements).
