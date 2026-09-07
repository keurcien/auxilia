# Skills preview

A skill is a `SKILL.md` file with YAML frontmatter, plus optional scripts and reference files:

```markdown
---
name: greeting
description: Use when greeting a new customer.
---
Greet the customer warmly. Run scripts/greet.py when needed.
```

Open **Skills → Create skill**, edit the file, add scripts, and click **Save**. Or import a ZIP containing `SKILL.md` and its supporting files. Export downloads the same portable bundle. YAML comments and extra frontmatter fields are preserved.

Enable skills using the checkboxes in an agent's settings. Saved changes apply to subsequent runs without publishing or selecting versions. Instructions work with any agent; running scripts requires a connected sandbox. Private skills are accessible to their owner and admins; share a skill with the workspace before attaching it to an agent used by others.

Agents see names and descriptions in the `read_skill` tool catalog. They load full instructions and supporting text on demand. Files are uploaded and verified when the sandbox connects, under `/tmp/auxilia-skills/<name>/<content-hash>/`. Sandbox edits do not change the saved files. Packages and CLIs come from the existing sandbox environment.

Postgres stores the skill and files. Binary files use base64; bundles are limited to 10 MB. In-flight runs keep a content snapshot so an edit cannot change their files during a retry or approval resume. This is internal execution state, with no user-facing history or version workflow.

## Updating the earlier preview

After checking out the updated branch, run `uv run alembic upgrade head` from `backend` (or use your normal startup migration), then restart the backend and web app.

The migration keeps the latest saved skill content and existing agent attachments. Previously selected versions are replaced by the latest saved content. Old history/test tables are renamed as migration backups for downgrade; the application does not use them or create new history. Existing test conversations remain ordinary conversations.

There are no AI editing tools, chat-to-skill shortcut, draft/publish workflow, example tests, version selections or Git integration.
