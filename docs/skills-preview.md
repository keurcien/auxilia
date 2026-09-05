# Skills preview

Branch: `feat/skills-preview`. No Git repository integration or synchronization is included.

## Try it

1. Check out the branch and start Auxilia with your normal configuration. Run `uv run alembic upgrade head` from `backend` if your startup does not already apply migrations. Use a test database; this adds skills tables and a run snapshot column.
2. Open **Skills → Create skill**. Give it a name, identifier, a description of when it applies, and a procedure. Save the draft.
3. In **Try & teach**, select an agent and model and try a prompt. The new conversation uses a frozen copy of that draft without changing the agent's published skills. Return to the skill to mark the result passed or failed and save useful examples.
4. Publish a version. In the **Agents** tab or an agent's editor, select that version. Publishing later versions does not update existing agent selections.
5. Chat with the agent. Its `read_skill` tool advertises short skill descriptions and loads instructions/resources on demand. Instruction skills work without a sandbox.
6. To test scripts, enable **Requires code execution**, add a file such as `scripts/check.py`, and attach the skill to an agent with a configured sandbox. After the sandbox connects, files are available under `/skills/<identifier>/<bundle-hash>/`. Invoke scripts through the sandbox's normal execution tools.

## Authoring and sharing

- Ask an agent to save a procedure as a reusable skill. **Save as skill** in an existing conversation prepares this request in the composer for you to review and send. Agents have tools to list/read editable skills and save drafts, but cannot publish through these tools.
- **Try & teach → Edit with AI** opens a conversation with the selected agent and an explicit draft-edit request. Save manual edits first. Review the resulting draft in the library before publishing.
- Private skills are readable by their owner and workspace admins. Workspace skills can be read and used by everyone; their owner and admins can edit them. A user running an agent must also have access to its skills. Share a skill with the workspace before using it on a shared agent.
- Required MCP connections and sandbox availability are checked when attaching a version and when running. The existing MCP authorization and action approval behavior still applies.
- **History** lets you restore an older version into the draft and export a standard `SKILL.md` ZIP. Import accepts one ZIP bundle or a standalone `SKILL.md`. Scripts, text references and binary assets are supported, with a 10 MB bundle limit.
- Export preserves the skill instructions, description, code requirement and files. Auxilia-specific test examples, display titles, MCP connection IDs, version history and sharing settings are not portable through this ZIP; configure these after import.

## Persistence and execution

Postgres is the source of truth: mutable drafts, immutable published bundles, agent version selections, draft test snapshots and run snapshots. Binary files are base64 encoded in bundle JSON. This deliberately keeps the preview provider-independent and requires no new object storage service.

At run creation, the worker freezes the selected bundles. Retries and interruption resumes reuse that snapshot, while checking current access and requirements. Agents and subagents receive their own catalogs. Sandbox files are uploaded and their bytes verified when the lazy sandbox connects.

Sandbox copies are writable; they are not operating-system read-only mounts. Edits never write back to the canonical bundle. Copy scripts into the working directory for ad hoc changes, or explicitly ask the agent to save updated content to a draft. Existing sandbox environments supply Python, CLIs and packages; skills do not build environments or automatically install dependencies. Each bundle uses a content-hashed directory, so removed or renamed files from older versions cannot remain at the current version’s paths. Old directories are retained until the sandbox is recycled.

## Validation and remaining limits

The implementation includes service/runtime tests for authorization, optimistic concurrency, immutable publishing, attachment compatibility, import validation, binary files, upload verification, frozen run snapshots and isolated draft tests. A route regression test checks the collection URL used by the web proxy.

Backend and frontend tests, TypeScript checking and a production frontend build were run locally. Browser smoke testing covered the library and draft authoring/publication using a disposable SQLite workspace. Live model-driven authoring and execution against a remote sandbox still need testing with your configured providers. Migration SQL was generated for Postgres, but a live Postgres migration could not be run in this environment.

Examples and passed/failed results are manual feedback, not automated evaluations. Bundle contents are copied into run snapshots; for large installations, deduplicated blobs or a provider-neutral object-store adapter would be a later optimization. There is no dependency lockfile, Git integration or automatic publication.
