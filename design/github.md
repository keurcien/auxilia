repo: keurcien/auxilia
branch: main

## Last sync
date: 2026-08-18T21:27:46Z
commit: 474fe0859c55

### Updated in this project
- Agent editor (12a): Code interpreter card expanded with a sandbox provider picker — Cloud Run (gVisor, GCS snapshots, no egress/TTL) vs OpenSandbox (managed remote, image + TTL) as radio cards — grounded in backend/app/sandbox/ (cloudrun/, opensandbox/, has_code_interpreter flag)
## Sync history
- 2026-08-11: Users page (13c) rethought (right-rail teams/invites); new 18a Settings (access tokens + workspace models); Triggers list (13a) reworked as a table; new 17a Trigger editor
- 2026-08-09: 14a MCP server detail rebuilt from mcp-server-dialog.tsx (page-based dialog config, display/edit modes, per-user revoke; later two-panel)
- 2026-08-08: Agents list tag tabs; MCP servers table (13b); new 14a MCP server detail with per-user revoke
- 2026-08-07: Agents list (7a) reworked (owner + subagents columns, tag filter, pagination); new screens 13a Triggers, 13b MCP servers, 13c Users from repo pages
- 2026-08-06: Editor screen (12a): three-state tool toggle rebuilt with the real check/hand/block icons and pill shape from three-state-toggle.tsx; "Disable {server}" footer action from agent-mcp-server.tsx
- 2026-08-02: Chat screen (8a) restyled to match current app structure: centered agent header, tall composer with model pill + round submit (from chat-header.tsx, prompt-input.tsx, message.tsx, tool.tsx)

## Screen map
| Screen | Repo files |
|---|---|
| Landing Page Options.dc.html | docs/content/index.mdx, README.md, web/src/app/globals.css, web/src/lib/colors.ts, docs/public/logo.svg |
| App Screens - Petrol Mono.dc.html | web/src/components/layout/app-sidebar/index.tsx, web/src/app/(protected)/agents/page.tsx, agent-card.tsx, agent-editor.tsx, agent-mcp-server.tsx, three-state-toggle.tsx, chat-header.tsx, mcp-server-dialog.tsx, mcp-server-create-form.ts, trigger-editor.tsx, trigger-detail.tsx, schedule-builder.tsx, next-runs-card.tsx, run-history-card.tsx, users/page.tsx, settings/page.tsx, create-token-dialog.tsx, workspace-models.tsx, agent-card.tsx, agent-list.tsx, trigger-card.tsx, triggers/page.tsx, mcp-server-card.tsx, mcp-servers/page.tsx, users/page.tsx, chat/components/prompt-input.tsx, ai-elements/message.tsx, ai-elements/tool.tsx |
