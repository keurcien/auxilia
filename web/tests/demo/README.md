# Demo video & docs screenshots

Playwright-driven tooling to record a product demo video and capture
screenshots for the Nextra docs. Everything runs against a **live stack**
— nothing is mocked, so the video shows real MCP tool calls. The frontend
is a **production build** (no dev-tools overlay, instant page loads); it
builds into its own dist dir (`.next-demo`) and serves on **:3100**, so a
`next dev` running on :3000 is unaffected.

## Prerequisites

1. A running backend with at least one LLM provider key in `.env`
   (e.g. `ANTHROPIC_API_KEY`):

   ```sh
   make dev-stack && make dev-backend    # postgres + redis + backend :8000
   ```

2. The production frontend for the recording (leave it running):

   ```sh
   cd web && npm run demo:web            # next build + next start on :3100
   ```

3. Playwright browsers installed once:

   ```sh
   cd web && npx playwright install chromium
   ```

## 1. Seed demo data

```sh
cd web && npm run demo:seed     # reconcile the seed on top of what exists
cd web && npm run demo:reset    # wipe agents/threads/triggers/MCP servers, then seed
```

`demo:reset` is the clean slate for a recording: it deletes **every** agent
(with its threads and checkpoints), trigger and MCP server in the workspace,
then seeds. Skills, sandboxes, users, teams and models are kept. It refuses
to run against a non-local `BACKEND_URL` unless `DEMO_RESET_REMOTE=1`.

`demo:seed` is reconciling (its own named resources are deleted and
recreated, so spec changes always converge) and leaves everything else alone.
Both create the first admin (`demo@auxilia.dev` / `auxilia-demo-123` —
override with `DEMO_EMAIL` / `DEMO_PASSWORD`) on a fresh workspace, then:

| | Seeded |
| --- | --- |
| MCP servers (7) | **Hugging Face** and **Context7** (public, no auth — the on-camera chats run against them); **Notion**, **Slack**, **HubSpot**, **BigQuery**, **GitHub** installed from the official catalog exactly as the one-click Add does (OAuth, connected per user later) |
| Agents (6) | **Docs Researcher** (Context7) · **Model Scout** (Hugging Face) · **Python Developer** (bound to the workspace's first sandbox, or `DEMO_SANDBOX_NAME`; skipped if none) · **Data Analyst** (BigQuery + Slack) · **HR Assistant** (Notion) · **Sales Assistant** (HubSpot + Slack) — each with real instructions |
| Teams + users | Data, Engineering, Marketing, Finance; display-only teammates Alice, Bob, John Doe for the sharing chapter |
| Model | Enables one and sets it as the workspace default if none is set |

It also uninstalls DeepWiki so the walkthrough can install it from the
catalog on camera. Targets `BACKEND_URL` (default `http://localhost:8000`).

The demo admin can only be created on a **fresh workspace** (first account).
If your workspace already has users, seed with your own admin account
instead — the same variables also drive the on-camera sign-in of the video:

```sh
DEMO_EMAIL=you@example.com DEMO_PASSWORD=... npm run demo:seed
```

For a from-scratch database (new admin, no other users), wipe the stack
first: `make reset && make dev`.

## 2. Record the demo video

```sh
cd web && npm run demo:video
```

(If you seeded with your own account, pass the same `DEMO_EMAIL` /
`DEMO_PASSWORD` here — they drive the on-camera sign-in.)

`tests/demo/walkthrough.demo.spec.ts` plays nine chapters on camera:

1. **MCP servers** — one-click install of **DeepWiki** from the official
   catalog (success toast), then the **Cloudflare Docs** custom-server form.
2. **Agents** — creates a **Research Assistant** (typed instructions,
   tool binding).
3. **Chat** — asks it a docs question and waits for the live MCP tool call.
4. **Skills** — writes a **docs-brief** skill in the Skills library (name,
   description, SKILL.md procedure), enables it on the Research Assistant
   with **Add skill**, and asks for a brief — the agent reads the SKILL.md
   and answers in the skill's format.
5. **Human in the loop** — flips a Research Assistant tool to
   **Needs approval**, asks again, and approves the paused tool call.
6. **Sharing** — in the Permissions tab, grants a seeded teammate Editor
   access and shares the agent with the Data and Marketing teams.
7. **Code execution** — opens the seeded **Python Developer** (sandbox-bound)
   and watches it run real Python (`Execute` steps).
8. **Triggers** — creates a **Daily model digest** trigger for Model Scout
   (agent picker, schedule builder, next-runs preview, detail page).
9. **HTTP API** — a terminal scene types the `runs/invoke` curl call while
   the request really runs against **Docs Researcher**; the printed reply
   is the agent's actual answer.

Human-paced typing and beats keep it watchable; pacing is scaled by
`DEMO_SPEED` (default 2 — beats, typing and cursor glides run twice as
fast; `DEMO_SPEED=1` restores the original feel). The terminal scene
follows the same factor; title cards keep their own pace.

Re-runs clean up all on-camera resources first (the trigger, the
agent, both MCP servers and the skill — server URLs and skill names are
unique).

The chapters are framed by **Petrol Mono title cards** (intro/close brand
cards and `// EYEBROW`-style interstitials, like a Remotion edit) injected
as full-screen overlays during the recording — no post-editing needed. A
fake **cursor** (petrol press ring) leads every click, since Playwright's
real pointer is invisible in recordings. The overlay components live in
`tests/utils/demo.ts` (`titleCard` / `brandCard` / `cursorClick` /
`apiScene`); copy and timings are set at the call sites in the spec.

Output: `web/demo-output/auxilia-demo.webm` (1440×900). Convert for sharing:

```sh
# -ss 0.3 trims the pre-first-paint blank: the mp4's poster frame is the logo
ffmpeg -ss 0.3 -i demo-output/auxilia-demo.webm -c:v libx264 -pix_fmt yuv420p demo-output/auxilia-demo.mp4
```

By default the demo/docs projects target `http://localhost:3100` (the
`npm run demo:web` production server). Point them elsewhere with
`PLAYWRIGHT_BASE_URL`. If you target a `next dev` server instead, use a
`localhost` URL — Next.js dev-origin protection 403s the JS chunks when the
page is addressed as `127.0.0.1`, leaving pages unhydrated.

## 2b. Record the Shopping assistant demo

```sh
cd web && npm run demo:video:shopping
```

`tests/demo/shopping.demo.spec.ts` is a second, shorter video about one agent
bound to the **Choose Shop** MCP server — an [MCP App](https://modelcontextprotocol.io/docs/extensions/apps):
its tool results render as an interactive carousel in a sandboxed iframe
inside the conversation. It is not seeded by `demo:seed`; it expects, in the
workspace the demo admin signs into:

- an agent named **Shopping assistant** (override with `DEMO_SHOPPING_AGENT`)
  bound to the Choose Shop server (`…/shop/mcp`, API-key auth) with all three
  tools (`search_sales`, `search_products`, `get_product`) allowed — the app
  drills down by calling them itself;
- the **DeepSeek V4 Pro** model enabled. The spec picks it in the composer on
  camera (unless it is the workspace default) together with reasoning effort
  **Off** — `DEMO_MODEL_NAME` / `DEMO_REASONING_EFFORT` override both. That
  configuration ran a single search for the gift prompt in 3 takes out of 5
  (Pro with thinking on: 1 in 3; Flash: never; Flash with thinking off went
  wild with 14–51 calls), so by default the spec re-records when that prompt
  produced more than one carousel (`DEMO_SINGLE_SEARCH=0` to accept
  multi-search takes). For the record, GPT-4o mini was single-search in 3/3
  trials; Claude and Gemini models fanned out into 2–10 searches.

Storyline: the product demo's intro card, then straight to the assistant's
starter screen — the session is authenticated with a cookie, so there is no
sign-in or agent picking on camera — a title slide about the assistant, then
two French-language parts:

1. **Entrée par les ventes** — "y a des ventes de mode homme en ce moment ?"
   (`DEMO_SALES_PROMPT`) → sales carousel → click the first sale (the app
   fetches its products) → add the first in-stock product to the (demo) cart
   → back. The men's-clothing wording of the original storyline is a valid
   override, but `search_sales` matches free text against the sale taxonomy
   and the carousel is empty whenever no live sale mentions "homme".
2. **Entrée par les produits** — a gift request with a budget
   (`DEMO_GIFT_PROMPT`) → one product search → open a product sheet → browse
   the gallery → add to cart.

An empty carousel (or a multi-search gift take, see above) fails the test and
Playwright re-records from scratch (`DEMO_RETRIES`, default 4) — a model can
still pick a filter that matches nothing.

The Choose carousel lives two iframes deep (`/sandbox.html` → a `blob:` app
page); the spec drives it with `frameLocator`s, so the cursor and clicks are
real. Re-runs delete the demo admin's previous threads on that agent first.

The UI steps run at `DEMO_SPEED=4` by default (twice the walkthrough's pace;
title cards keep their own timing) — override the variable to slow down.

Output: `web/demo-output/auxilia-shopping-demo.webm` (1440×900); convert with
the same ffmpeg command as above.

## 3. Capture docs screenshots

```sh
cd web && npm run docs:screenshots
```

`tests/docs/screenshots.docs.spec.ts` writes light-mode 1440×900 PNGs
(rendered at 2× for crisp docs images) to `docs/public/screenshots/`
(override with `DOCS_SCREENSHOT_DIR`). Several shots feature what the demo
walkthrough leaves behind — record the demo first for the richest set; each
falls back to seeded data otherwise.

| File | Page |
| --- | --- |
| `auth.png` | Sign-in |
| `agents.png` | Agents list |
| `agent-detail.png` | Agent detail (Research Assistant) |
| `agent-editor.png` | Agent editor in edit mode (tools + skills) |
| `agent-tool-settings.png` | Expanded server card — per-tool three-state toggles |
| `agent-add-tool-dialog.png` | "Add tool" dialog (MCP servers + sandboxes) |
| `agent-skills.png` | "Add skill" dialog |
| `agent-permissions.png` | Permissions tab (people + teams) |
| `chat.png` | Chat starter screen |
| `chat-tool-call.png` | A finished turn with the "Worked" steps expanded |
| `chat-approval.png` | Human-in-the-loop approval card |
| `mcp-servers.png` | MCP servers list |
| `mcp-server-catalog.png` | Add server — catalog |
| `mcp-server-custom.png` | Add server — custom form (pre-filled) |
| `skills-library.png` | Skills library |
| `skill-detail.png` | Skill detail (docs-brief) |
| `skill-new.png` | New skill editor (pre-filled) |
| `skills-sources.png` | Skills — Sources tab |
| `skill-source-new.png` | Connect a repository, with preview |
| `triggers.png` | Triggers list |
| `trigger-detail.png` | Trigger detail (Daily model digest) |
| `trigger-new.png` | New trigger (pre-filled, next-runs preview) |
| `settings-tokens.png` | Settings — Access tokens |
| `settings-models.png` | Settings — Models |
| `settings-sandboxes.png` | Settings — Sandboxes |
| `sandbox-dialog-opensandbox.png` | Add sandbox — OpenSandbox form (pre-filled) |
| `sandbox-dialog-daytona.png` | Add sandbox — Daytona form (pre-filled) |
| `users.png` | Users and teams |

The docs pages reference these from the CDN, not from `/screenshots/`:
upload the PNGs to the `docs/` prefix of the bucket
(`https://pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev/docs/<name>.png`) and
embed them in MDX as:

```mdx
![Agents](https://pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev/docs/agents.png)
```

Add a new shot by appending a test to the spec and calling
`docShot(page, "name")` from `tests/utils/docshot.ts`.

## Layout

```
tests/
├── demo/
│   ├── seed-demo.mjs               # zero-dep DB seeding via the backend API
│   └── walkthrough.demo.spec.ts    # the recorded demo (project: demo)
├── docs/
│   └── screenshots.docs.spec.ts    # docs screenshots (project: docs)
└── utils/
    ├── demo.ts                     # auth/API helpers, pacing, cleanup
    └── docshot.ts                  # screenshot writer for docs/public/
```

The `demo` and `docs` Playwright projects live alongside the existing
`visual` project in `playwright.config.ts`; `npm run test:visual` is
unaffected.
