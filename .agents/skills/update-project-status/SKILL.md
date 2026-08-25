---
name: update-project-status
description: >-
  Use this skill to update the project-status.json file and summarize the work done.
  Any agent who has completed a feature or made significant code changes should run this
  to reflect the progress in the project status.
---

# Update Project Status Skill

When invoked, perform the following steps to update the project status:

1. **Review Recent Changes**: Look at the current Git diffs or the most recent commits to understand what feature was just implemented.
2. **Consult Business Blueprint**: Check `.agents/rules/business_blueprint.md` to identify which Epic and Business Rules the recent changes belong to.
3. **Update `project-status.json`**:
   - Locate `project-status.json` in the root of the app.
   - Update the `completion_percentage` and `status` (To Do, In Progress, Done) of the relevant Epic.
   - Update the `current_focus` string to describe what is currently being worked on or what was just finished.
4. **Report**: Inform the user about what was updated in the project status tracker.
