# Handoff: Auxilia — Petrol Mono redesign

## Overview
A full visual redesign of Auxilia (open-source MCP client for teams, keurcien/auxilia) called **Petrol Mono**: geometric sans + mono accents, white canvas, petrol teal (#16606E) as the single accent. Covers the docs landing page and app screens: Agents list, Agent editor (two-panel config, testing happens in real chat), Chat (chain-of-thought tool calls, subagent calls), Triggers, MCP servers (list + detail + add flow), Users, Workspace settings (tokens + models), and Login.

## About the Design Files
The files in this bundle are **design references created in HTML** — prototypes showing intended look and behavior, not production code to copy. The task is to **recreate these designs inside the existing Auxilia codebase** (Next.js App Router + Tailwind + shadcn/radix, `web/src`), replacing the current sage-green system, using the repo's established patterns (e.g. keep `components/ai-elements`, `app-sidebar`, class-variance patterns).

## Fidelity
**High-fidelity.** Colors, typography, spacing and states are final; recreate pixel-perfectly with Tailwind utilities / CSS vars.

## Files in this bundle
- `Petrol Mono Design System.dc.html` — **the UI kit / source of truth**: color tokens, type scale, buttons, forms, badges, navigation, list rows, chain-of-thought, chat & composer, dark panel, layout & radii. Open it in a browser.
- `App Screens - Petrol Mono.dc.html` — working screens. Section ids: 9a Login, 8a Chat, 7a Agents list, **12a Agent editor (the chosen editor design)**, 13a Triggers list, 17a Trigger editor, 13b MCP servers list, 14a MCP server detail, 15a Add MCP server (catalog), 15b Add MCP server (custom form), 13c Users, 18a Settings, 19a Dialog patterns (2b/3b/4a/5a/10a/10b/10c/11a are earlier iterations — ignore).
- `Landing Page Options.dc.html` — section 1c "Petrol Mono" is the chosen landing direction (1a/1b are discarded explorations).

## Design tokens

### Fonts (Google Fonts)
- **Space Grotesk** 700, letter-spacing -0.035em — display only: page H1s (28–68px), wordmark, landing card titles. Never in rows/nav/body.
- **Hanken Grotesk** 400–700 — all UI text. Body 14.5px/1.6; controls 13–14px w500–600; descriptions 12–13px.
- **IBM Plex Mono** 400–600 — the signature: eyebrows (`// LIKE THIS`, 11.5px w500 teal, +0.07em), field labels (10.5px w600 caps +0.09em #6E7C80), agent names (12.5px w600 **#16606E**), metadata/timestamps/counts (10–11px #8A9AA0), breadcrumbs (11.5px, slugs), terminal & code (11.5–13px).

### Light palette
| Token | Hex | Use |
|---|---|---|
| ink | #101820 | text, primary buttons, dark panel bg |
| teal (accent) | #16606E | agent names, save/confirm, active tab underline, submit, links |
| body | #46545A | body/intro text |
| secondary | #56646A / #6E7C80 | secondary text, labels |
| muted | #8A9AA0 | placeholders, meta |
| faint | #A8B4B8 / #C4CED0 | timestamps, chevrons, disabled |
| canvas | #FFFFFF app · #F6F8F8 marketing/login |
| sidebar | #FBFCFC |
| hover / user bubble / code bg | #F1F5F5 |
| active/selected tint | #EDF3F3 (also #E3EEEE chips) |
| borders | #E9EEEE hairline · #DCE4E4 inputs/buttons · #E2E8E8 rails |
| sparkline | #B9D6DB |

### Status
- success/allowed/running: #1E7A56 on #E1F3EC
- warning/approval/unsaved: #B07A2A on #FBF3E2
- neutral/disabled/member: #8A9AA0 on #EDF1F1

### Dialogs / modals
Overlay: rgba(10,25,30,0.45), no blur. Panel: white, **14px radius**, 1px #E9EEEE border, shadow `0 24px 64px -16px rgba(10,25,30,0.28)`; width 480px (forms 560px), padding 24px. Header: Hanken title **16/700** ink + optional 13px #6E7C80 description under it, grey ✕ close top-right (28px hit, hover #F1F5F5). Body reuses editor form patterns verbatim: 13/600 field labels, bordered inputs (8px radius, #DCE4E4, teal focus ring rgba(22,96,110,0.10)), mono for technical values, mono-caps 10.5/600 section labels for grouped content. Footer: right-aligned row, gap 8px — outline Cancel (1px #DCE4E4, 7px radius, 13/600) + teal #16606E primary (white 13/600, 8px 18px padding); destructive confirm = #B04A3A fill with the same geometry, never a bare red text button in a footer. One-time secrets inside dialogs use the reveal-banner pattern from Settings (teal-tinted #F2F8F8, #B9D6DB border, mono token + Copy). No pill radii, no centered footers, no icon-decorated titles.

### Dark panel (landing terminal, login showcase)
bg #101820 · cards rgba(255,255,255,0.04) with rgba(255,255,255,0.08–0.10) borders · terminal text #9FD6CB · dim #5A6E74 · success #7BC7A9 · attention #E8A085 (border 35%, fill 7%) · body #C9D4D6 · strong values #FFFFFF bold · primary button on dark = light #E6EDEE fill, ink text. Optional 40px grid overlay: 1px lines rgba(159,214,203,0.05).

### Agent pastels (avatar tiles ONLY)
#D0F5EA #E4DFFF #FFE0D9 #FFF5CC #D6EAFF #FBE3EE. Emoji on pastel tile: 22/28/32/48px, radius ≈ size/4; round (999px) only in chat header & thread rows. Humans: ink circle + white initials.

### Radii
4px badges · 6–7px chips/buttons/nav · 8px inputs · 10–12px containers/tool cards · 16px composer · 999px pills/round buttons.

### Shadows
Almost none: 0 1px 2px rgba(10,25,30,0.04) raised buttons; 0 8px 24px -12px rgba(10,25,30,0.08) composer; teal submit glow 0 4px 12px -4px rgba(22,96,110,0.4). Depth comes from borders.

### Spacing
Base 4px; common steps 8/12/16/20/24/32. App shell: sidebar 248px, top bar ~52px, content padding 32px, chat/reading column max-width 780px.

## Screens

### Agents list (7a)
Top bar: mono breadcrumb `workspace / agents`, search (320px, ⌘K kbd), ink "+ New agent". Header: Space Grotesk "Agents" 30/700 + Hanken intro line; right: underline tabs (Available to you / All / Archived) + ☰/▦ view toggle. Below the header: **dropdown filter buttons** — "Tag · All ⌄" and "Owner · Anyone ⌄" (lucide tag/user icon 12px, bordered 7px chips, value in ink w600). Table: mono caps column headers (AGENT / MCP SERVERS / SUBAGENTS / OWNER / ACCESS) — no analytics columns; info parity with card view. **Rows grouped by tag**: sub-header rows on #FBFCFC inside the bordered container (same pattern as Settings→Models provider groups) — lucide tag icon 11px + mono-caps tag name 10/600 #6E7C80 + right-aligned mono count; untagged agents grouped last under `OTHERS`; the Tag dropdown filter narrows to one tag. Rows in bordered 10px container, #F1F5F5 dividers, hover #FBFCFC. Row = 32px emoji tile + teal mono agent name + grey description; MCP servers = 24px favicon chips (bordered, white); subagents = 22px emoji circles on their pastels; owner = 22px ink initials circle + name; role badge. Footer: `1–6 of 12 agents` mono + numbered pagination (28px squares, active = teal fill, disabled arrow = faint border).

### Agent editor (12a)
No in-editor playground — testing opens the real chat with the draft config. Full-width header bar: mono breadcrumb `agents / data-analyst`, UNSAVED badge (#B07A2A on #FBF3E2), right: "▷ Test in chat" (outline, teal text) / Discard (outline) / Save changes (teal fill). Below, two panels:
**Left (white) — definition.** Identity header: 48px emoji pastel tile with a small pencil badge at its corner (opens emoji picker); name + description as always-visible bordered inputs (8px radius, #DCE4E4 border, teal focus ring; placeholders "Agent name" / "Describe what this agent does" for the new-agent case). Underline tabs (Instructions / Access). INSTRUCTIONS textarea (mono 12.5 on #FBFCFC, teal focus ring). MODEL selector row (favicon + name + ⌄).
**Right (#FBFCFC) — capabilities.** `MCP SERVERS` mono-caps header + "+ Add server". One card per server, always expanded (page scrolls; no "N more tools" pagination, no per-server ALLOW/ASK counts): header = 26px favicon chip + server name (sans 13.5/600, capitalized) + collapse ⌄; tool rows = humanized tool name 13.5/600 + the tool's description 12px #6E7C80; per-tool **three-state toggle** (from `ui/three-state-toggle.tsx`): pill #F1F5F5 with check / hand / block lucide icons, active = white pill + shadow, tooltips "Always allow / Needs approval / Disabled"; disabled tools grey out. Card footer: centered red "Disable {server}" (#B04A3A). **Code interpreter** = card: header row (26px 🧮 tile on #EDF3F3 + name 13.5/600 + "built-in" grey + red "Disable", on #FBFCFC) + sandbox picker under a hairline — helper line ("Runs code in an isolated Linux environment. Choose where it runs:") + two radio cards (auth-card style: selected = teal border + #F7FAFA + soft teal ring): **Cloud Run** (favicon, "gVisor-isolated, self-hosted. State snapshots to GCS between turns.", mono `no egress · no TTL`) vs **OpenSandbox** (ink "O" glyph tile, "Managed remote sandboxes. Lives across turns until its TTL expires.", mono `image: python-datasci · ttl 60 min`). `SUBAGENTS` header + "+ Add subagent"; rows = 32px emoji tile + teal mono name + description + ✕ (no call counts).

### Chat (8a)
Centered 56px header: round avatar + agent name. User msgs: #F1F5F5 bubble radius 12/12/3/12, max 78%. Assistant: plain full-width text.
**Chain of thought (replaces stacked tool cards):** mid-air, no container. Header row "✦ Worked for Ns · N tool calls · N subagent" (collapsible). Steps hang on a 1px #E2E8E8 rail: 22px node = MCP favicon chip; humanized tool name (run_query → "Run query") 13.5/600 ink; plain-language argument summary #6E7C80; duration mono; each step collapsible → indented 34px: PARAMETERS / RESULT mono-caps labels + code on #F1F5F5 (6px radius, no border).
**Subagent calls are steps too:** node = subagent emoji on its pastel tile, name = "Ask {Agent}", expanded = TASK block → nested rail with the subagent's own tool calls and ✦ italic reasoning lines (one nesting level max) → RESULT block.
Composer: 16px radius, 2px #DCE4E4 border (focus #16606E), textarea top; footer: + attachment pill, model pill (favicon + name, #F1F5F5, 999px), round 38px teal submit ↑.

### Triggers (13a list · 17a editor)
**List (13a):** table consistent with the agents list. Columns: TRIGGER (32px ⏱ tile on #EDF3F3 + teal mono name 12.5/600 + instruction excerpt 12px grey) / AGENT (22px emoji pastel circle + name) / SCHEDULE (mono 11, e.g. `once a week · mon 09:00`) / NEXT RUN (mono 11; paused = `paused` in #A8B4B8) / STATUS on-off toggle (34×20 pill, on = teal, off = #DCE4E4 knob left) / ⋮. Bordered 10px container, #F1F5F5 dividers, hover #FBFCFC; `1–4 of 4 triggers` footer. Row click → 17a.
**Editor (17a):** two panels like the agent editor (56px icon rail, Triggers active). Header bar: mono breadcrumb `triggers / weekly-gmv-recap`, UNSAVED badge, actions: delete icon button (red #B04A3A on #F0D5D0 border) / "▷ Run now" (outline teal) / Discard / teal Save changes. **Left (white) — definition:** 48px ⏱ tile + bordered mono name input (teal text, placeholder "What does this trigger do?"), Active toggle + green "Active" + · + mono "next run …" line; `AGENT` picker row (emoji circle + teal mono name + "runs with this agent's servers and guardrails" + ⌄); `INSTRUCTIONS` card on #FBFCFC (mono 12.5 textarea, placeholder "The message sent to the agent on every run…") with model picker chip in a bordered footer row. **Right (#FBFCFC) — schedule:** `FREQUENCY` white card: preset dropdown (Every day / Weekdays / Once a week / Every two weeks / Once a month / Custom…) · "at" · time field (clock icon, mono); "On" + 7 day chips (34px, equal flex, selected = ink #101820 fill); summary line on #F7FAFA (repeat icon teal + "Every Monday at 09:00" + mono timezone right); embedded `NEXT RUNS` under a hairline (26px circle + dot rows — first teal dot + 600 text, rest #C4CED0 + 500). `RUN HISTORY` (hint "last 30 days") white card: date rows opening threads; states = RUNNING (teal spinner, mono caps) / FAILED (✕ #B04A3A) / plain `opens thread ›`.

### MCP servers (13b list · 14a detail)
**List (13b):** list only (no card grid, no view toggle). Columns: SERVER (32px logo tile with 0 2px 6px shadow + name 13.5/600 + description 12px grey) / ENDPOINT (mono 11 grey) / AUTH badge (`OAUTH 2.1` #2E6FA8 on #E7F0FA · `API KEY` #6E7C80 on #EDF1F1; repo auth enum none/api_key/oauth2) / TOOLS count (mono) / CONNECTIONS (`11/14 users` for OAuth, `workspace key` for API key) / always-visible row actions: Test (teal) · Edit · ⋮. Row click → detail page.
**Add server (15a catalog · 15b custom):** 15a — page (not modal): title "Add an MCP server", search field only (no category pills), 3-col catalog cards: 38px logo tile + name 14.5/700 + auth badge + mono endpoint + description, footer = right-aligned teal `Add` button (installed → grey `✓ Added`), no divider line in card; below, dashed "Add a custom server" row (plus icon on #EDF3F3) → 15b. 15b — centered 640px form, `‹ Catalog` back link, header Cancel / teal Add server (disabled at 0.5 until address valid): required Remote server address (mono input + auto-discovery hint), Name + optional Icon URL side by side, optional Description, **Authentication method = three radio cards** (None "Open endpoint" / API key "One shared key for the whole workspace" / OAuth 2.0 "Each user connects their own account"; selected = teal border + #F7FAFA + soft teal ring); OAuth panel on #FBFCFC: DCR helper ("leave both blank to use Dynamic Client Registration"), optional Client ID (mono), write-only Client secret with eye toggle, copyable Callback URL row; "Test before adding" row (check icon tile + copy + outline teal Test connection).
**Detail (14a, OAuth example):** two panels like the agent editor. Full-width header bar: breadcrumb `workspace / mcp-servers / notion` + actions Test connection / Edit server / ⋮ (edit mode: Test connection / Cancel / teal Save changes). **Left panel (white)**: 52px logo tile (0 2px 8px shadow) + Space Grotesk name 26/700 + `OAUTH 2.0` badge + grey `Official` pill + mono endpoint; `CONFIGURATION` mirrors mcp-server-dialog.tsx — display mode = label/value rows (200px label col 13/600 #46545A, #F1F5F5 hairlines): Name, Remote server address (mono), Icon URL (mono), Description, Authentication method (read-only), Client ID (mono), Client secret as masked last-4 `••••3kfa` + "write-only"; edit mode = bordered inputs (8px radius #DCE4E4, teal focus ring), required \* on address, auth fixed ("can't be changed after creation"), dialog helper copy, secret input with masked placeholder + eye toggle, footer red "Delete server" + "Reset connections". **Right panel (#FBFCFC)**: `CONNECTED USERS` (n of m) header + red "Reset all connections"; one white bordered card filling the panel height (internal scroll, no "show more") listing every user: 32px initials circle + name + mono email, mono "connected mar 12", status badge (ACTIVE green / EXPIRED amber with skipped-runs tooltip), per-user Revoke (red text button, hover #FBEFED).

### Users (13c)
Header: "Users" + ink "+ Invite user". Two-column layout: **main column** — role filter chips (All/Admins/Editors/Members, active = #EDF3F3 teal), members table: NAME (32px initials circle + name + `YOU` badge #EDF3F3 teal mono 9px) / EMAIL (mono 11.5 grey) / ROLE dropdown chip (dot: admin #1E7A56, editor #B07A2A, member #8A9AA0) / TEAM dropdown chip (team color dot; "No team" = dashed border, grey) / remove ✕ (hover red); pagination as agents list. **Right rail (330px)** — `TEAMS` (bordered list: color dot 9px + name + `n members` mono + ⋮; "+ New team" teal link) and `PENDING INVITES` (stacked card: dashed ✉ circle + mono email + invited-by meta, second row = amber "Member invite" pill + Copy link / red Revoke). Teams are user groups (they don't filter agents); tags are per-agent labels. Sidebar Workspace nav includes Settings after Users.

### Settings (18a)
Breadcrumb `workspace / settings`. Left anchor nav (200px, like the editor pages): small Space Grotesk "Settings" 22/700 title above the nav; items "Access tokens" / "Models" with mono counts; active = 2px teal left border + w600 ink, inactive grey. Each item is a separate tab/screen — the content column swaps entirely (no shared page H1).
**Access tokens tab:** `PERSONAL ACCESS TOKENS` mono-caps header + ink "+ Generate token"; helper line ("Authenticate external services against the API — n8n, the invoke endpoint, scripts. Tokens act as you."); one-time reveal banner (teal-tinted #F2F8F8, #B9D6DB border, key icon tile): "Copy your new token now — you won't be able to see it again." + full mono token + teal Copy button; token table: TOKEN (name 13.5/600 + mono truncated prefix `aux_pat_9f2c…`) / CREATED (mono date) / revoke trash icon (hover red on #FBEFED).
**Models tab (admin):** `WORKSPACE MODELS` header + `admin` mono hint + outline teal "Sync catalog" (refresh icon); helper copy (members pick from enabled models; new catalog models start disabled; star = workspace default, preselects pickers, else first available). One bordered container, provider group sub-headers on #FBFCFC (`ANTHROPIC` / `OPENAI` / `GOOGLE` + `n/m enabled` right-aligned); model rows: 16px provider favicon (dimmed when disabled) + name 13.5/600 + badges (`DEFAULT` teal on #EDF3F3 · `MULTIMODAL`/`STRUCTURED OUTPUT` grey on #F1F5F5 · `NO LONGER SUPPORTED` red on #FBEFED) + mono model id under; right: star toggle (filled ink = default) + enable toggle. Disabled rows grey out.
### Login (9a) logo + wordmark + v1.x chip; `// WELCOME BACK` eyebrow; Space Grotesk 40px "Sign in to your workspace"; EMAIL/PASSWORD mono labels; ink "Sign in →"; mono OR divider; Google button; mono footer (self-hosted · AGPL-3.0). Right: dark panel with 40px grid overlay, `// AGENTS THAT WORK LIKE YOUR TEAM`, and an **animated loop** (~1.3s/step, 8 steps, fade+8px rise): user question → "data-analyst is working…" → 3 tool lines (favicon, name, meta, ok) → answer with bold values → "HUMANS STAY IN CONTROL" approval card → mono footer stats. Content is generic product showcase — nothing user-specific pre-auth.

### Landing (1c in Landing Page Options)
Nav with v1.x chip; `// OPEN-SOURCE MCP CLIENT FOR TEAMS` eyebrow; Space Grotesk 68px headline; $ git clone terminal chip with copy; demo placeholder; 4-column numbered feature strip (01 — AGENTS…) in a single bordered container; agent slug chips; mono footer.

## Interactions
- Hover: rows #FBFCFC; sidebar items #F1F5F5; buttons darken border (#B9CDD0). No teal left-border on active nav (removed deliberately) — active = #EDF3F3 bg + w600.
- Focus: inputs teal border + 3px rgba(22,96,110,0.10) ring.
- Chain-of-thought steps expand/collapse individually; whole chain collapses to the "Worked for Ns" row. Default: collapsed once run is done, open while streaming.
- Approval flows: amber/coral treatment (light: #B07A2A/#FBF3E2 badge · dark: #E8A085 card) with Approve/Deny.
- Login demo loops forever; respect prefers-reduced-motion.

## Voice
Sentence case everywhere; ALL-CAPS reserved for mono labels/badges. No emoji outside agent avatars. Humanize tool names in UI (search_web → "Search web").

## Assets
- Logo: `docs/public/logo.svg` (+ logo-dark.svg) from the repo.
- MCP/provider icons: favicons via `https://www.google.com/s2/favicons?domain=<domain>&sz=64` in prototypes — in production use each MCP server's stored icon (fallback: first-letter tile, see existing tool.tsx).

## Suggested implementation order
1. Tokens: fonts + CSS variables (replace sage palette in `globals.css`).
2. Sidebar (`components/layout/app-sidebar`) — order: New thread → Recent threads → Workspace (Agents / Triggers / MCP Servers / Users / Settings) → user card.
3. Agents page (list view) · 4. Agent editor · 5. Chat: restyle `ai-elements/tool.tsx` into the chain-of-thought (+ subagent step) · 6. Triggers / MCP servers (list + detail + add) / Users / Settings · 7. Login · 8. Docs landing.
