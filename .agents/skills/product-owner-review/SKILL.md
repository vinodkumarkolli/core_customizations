---
name: product-owner-review
description: >-
  Use this skill to perform a Product Owner review of the codebase. 
  Triggers the Product Owner persona to audit recent changes against the Business Blueprint.
---

# Product Owner Review Skill

When invoked, the agent assumes the role of the Product Owner / Scrum Master and performs the following:

1. **Verify Blueprint Alignment**: Cross-reference the latest Python and JS changes with `.agents/rules/business_blueprint.md`. Ensure that no business rules were violated (e.g., ensuring Delivery Notes are still required for Wholesale flow).
2. **Audit Metadata Tags**: Check that all new complex logic contains the mandatory `@businessRule [BR-XXX-XXX]` inline comments.
3. **Review Fixtures Registry**: Ensure any structural schema changes (like adding new Custom Fields) were properly documented in `docs/FIXTURES_REGISTRY.md`.
4. **Acceptance Criteria**: If the tests (`bench run-tests`) are passing and the metadata is complete, formally approve the feature. If not, generate a punch-list of missing business requirements for the developer.
