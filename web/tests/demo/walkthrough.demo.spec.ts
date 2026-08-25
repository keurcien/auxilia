import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import {
	agentIdByName,
	api,
	apiScene,
	beat,
	brandCard,
	cursorClick,
	DEMO_EMAIL,
	DEMO_PASSWORD,
	ensureWalkthroughAgentTools,
	humanType,
	paced,
	resetWalkthroughResources,
	titleCard,
	WALKTHROUGH,
} from "../utils/demo";

/**
 * Records the product demo as a video (Playwright's built-in recorder).
 *
 * Storyline (each chapter opens on a title card): sign in → add MCP servers
 * (catalog + custom) → build an agent → chat with a live tool call → human
 * in the loop (flip a tool to "Needs approval", approve on camera) → share
 * the agent (person + teams in the Permissions tab) → run code in a sandbox
 * → schedule a trigger → call an agent over HTTP (real invoke, rendered in
 * a terminal scene) → close card.
 *
 * The title cards, fake cursor and terminal scene are Petrol Mono overlays
 * injected during recording (tests/utils/demo.ts) — no post-editing.
 *
 * Prerequisites: a running backend, a production frontend
 * (npm run demo:web → next start on :3100) seeded with `npm run demo:seed`.
 *
 * Run: npm run demo:video
 * Output: web/demo-output/auxilia-demo.webm
 */

const OUTPUT = path.join(process.cwd(), "demo-output", "auxilia-demo.webm");

const TAGLINE = "The open-source MCP client for teams";

test.beforeAll(async () => {
	// The walkthrough creates these on camera; MCP server URLs are unique,
	// so remove leftovers from a previous recording.
	await resetWalkthroughResources();
});

test("demo walkthrough", async ({ page, baseURL }) => {
	await page.emulateMedia({ colorScheme: "light" });
	await page.context().addCookies([
		{ name: "sidebar_state", value: "true", domain: new URL(baseURL!).hostname, path: "/" },
	]);

	await test.step("intro card", async () => {
		// A cover from the very first paint of /auth, showing the full
		// logo+wordmark lockup at the exact spot the intro card will render it
		// — the video's poster frame (e.g. GitHub's preview) is the brand, not
		// a blank page or the loading sign-in screen. It's an html::before
		// pseudo-element injected into the SERVER-rendered <head> via route
		// interception (an init-script DOM node doesn't reliably survive React
		// hydration). The lockup is a pre-rendered screenshot of the card's own
		// row (tests/demo/assets/brand-row.png) inlined as a data URI — text
		// can't be CSS-painted before the webfont loads. brandCard removes the
		// cover once the card (logo and wordmark static) is up. Rect measured
		// at the 1440×900 recording viewport: (567, 384) 306×76 — recapture the
		// asset with a clip screenshot if the card's brand row ever changes.
		const rowUri = `data:image/png;base64,${fs
			.readFileSync(path.join(process.cwd(), "tests", "demo", "assets", "brand-row.png"))
			.toString("base64")}`;
		const coverStyle =
			'<style id="__demo_cover">html::before{content:"";position:fixed;' +
			`inset:0;z-index:2147483646;background:#fff url("${rowUri}") ` +
			"567px 384px / 306px 76px no-repeat;}</style>";
		await page.route(
			(url) => url.pathname === "/auth",
			async (route) => {
				if (route.request().resourceType() !== "document") return route.continue();
				const response = await route.fetch();
				const body = (await response.text()).replace("</head>", `${coverStyle}</head>`);
				await route.fulfill({ response, body });
			},
		);
		await page.goto("/auth");
		await page.unrouteAll();
		await brandCard(page, { tagline: TAGLINE, holdMs: 2200, instant: true });
	});

	await test.step("sign in", async () => {
		await expect(page.locator("#email")).toBeVisible();
		await beat(page, 1200);
		await humanType(page, "#email", DEMO_EMAIL);
		await humanType(page, "#password", DEMO_PASSWORD);
		await beat(page, 400);
		await cursorClick(page, page.getByRole("button", { name: /sign in/i }));
		await page.waitForURL("**/agents**");
		// Let the seeded agents render so the workspace looks alive.
		await beat(page, 2200);
	});

	await test.step("add MCP servers", async () => {
		await titleCard(page, {
			index: 1,
			total: 8,
			eyebrow: "// MCP SERVERS",
			title: "Connect your tools",
			sub: "One-click installs from the official catalog — or any remote MCP server.",
		});
		await cursorClick(page, page.getByRole("link", { name: "MCP Servers" }));
		await page.waitForURL("**/mcp-servers");
		await beat(page, 1800);

		await cursorClick(page, page.getByRole("button", { name: "Add MCP server" }));
		await page.waitForURL("**/mcp-servers/add");
		await beat(page, 1600);

		// Install an official catalog server with one click. The card has no
		// test id — the innermost div containing both the endpoint URL and an
		// Add button is the card root.
		const catalogCard = page
			.locator("div")
			.filter({ hasText: WALKTHROUGH.catalogServerUrl })
			.filter({ has: page.getByRole("button", { name: "Add", exact: true }) })
			.last();
		await cursorClick(page, catalogCard.getByRole("button", { name: "Add", exact: true }), {
			timeout: 20_000,
		});
		// The card flips to "✓ Added" and a success toast confirms the install.
		await expect(catalogCard.getByText("✓ Added")).toBeVisible({ timeout: 15_000 });
		await expect(
			page.getByText(`${WALKTHROUGH.catalogServerName} added to the workspace`),
		).toBeVisible();
		await beat(page, 2400);

		await cursorClick(page, page.getByRole("link", { name: /Add a custom server/ }));
		await page.waitForURL("**/mcp-servers/add/custom**");
		await beat(page, 800);

		await humanType(page, "#mcp-url", WALKTHROUGH.serverUrl);
		await humanType(page, "#mcp-name", WALKTHROUGH.serverName);
		// The icon URL is long — paste it instead of typing it out on camera.
		await page.locator("#mcp-icon-url").click();
		await page.locator("#mcp-icon-url").fill(WALKTHROUGH.serverIconUrl);
		await humanType(page, "#mcp-description", WALKTHROUGH.serverDescription);
		await beat(page, 600);

		await cursorClick(page, page.getByRole("button", { name: "Add server" }));
		await page.waitForURL(
			(url) => url.pathname === "/mcp-servers" || /^\/mcp-servers\/[0-9a-f-]{36}/.test(url.pathname),
			{ timeout: 30_000 },
		);
		// Success toast for the custom server too.
		await expect(
			page.getByText(`${WALKTHROUGH.serverName} added to the workspace`),
		).toBeVisible();
		await beat(page, 2400);
	});

	let agentUrl = "";

	await test.step("create and instruct an agent", async () => {
		await titleCard(page, {
			index: 2,
			total: 8,
			eyebrow: "// AGENTS",
			title: "Build an agent",
			sub: "Instructions plus the tools it may use — that's the whole setup.",
		});
		await cursorClick(page, page.getByRole("link", { name: "Agents" }));
		await page.waitForURL("**/agents");
		await beat(page, 1200);

		await cursorClick(page, page.getByRole("button", { name: "New agent" }));
		await page.waitForURL("**/agents/new");
		await beat(page, 800);

		await humanType(page, 'input[placeholder="Agent name"]', WALKTHROUGH.agentName);
		await humanType(
			page,
			'input[placeholder="Describe what this agent does"]',
			"Answers questions from the official documentation.",
		);
		const instructions = page.getByPlaceholder(/Enter instructions for your agent/);
		await cursorClick(page, instructions);
		await instructions.pressSequentially(
			"You are a research assistant. When the user asks a technical question, " +
				"search the documentation with your tools before answering, and base " +
				"your answer on what you find. Keep answers short and cite your source.",
			{ delay: paced(12) },
		);
		await beat(page, 800);

		// Bind the MCP server added a minute ago.
		await cursorClick(page, page.getByRole("button", { name: "Add tool" }));
		const dialog = page.getByRole("dialog");
		await expect(dialog).toBeVisible();
		await beat(page, 900);
		await cursorClick(
			page,
			dialog.getByRole("button", { name: `Add ${WALKTHROUGH.serverName}` }),
		);
		await beat(page, 700);
		if (await dialog.isVisible()) await page.keyboard.press("Escape");

		// The server card fetches the remote server's tools on mount and seeds
		// the draft tool map — wait for the CONNECTED badge (it flips exactly
		// when the tools arrive) so the agent isn't saved with an empty map.
		await expect(page.getByText("CONNECTED", { exact: true })).toBeVisible({
			timeout: 30_000,
		});
		await beat(page, 1200);

		await cursorClick(page, page.getByRole("button", { name: "Create agent" }));
		await page.waitForURL(/\/agents\/[0-9a-f-]{36}$/, { timeout: 30_000 });
		agentUrl = page.url();
		// Off-camera safety net: make sure the tool map is persisted even if
		// the seed hadn't landed in the draft when we hit Create.
		await ensureWalkthroughAgentTools(agentUrl);
		await beat(page, 2000);
	});

	await test.step("chat with the agent", async () => {
		await titleCard(page, {
			index: 3,
			total: 8,
			eyebrow: "// CHAT",
			title: "Put it to work",
			sub: "Ask a question and watch it call your tools, live.",
		});
		await cursorClick(page, page.getByRole("button", { name: "Test in chat" }));
		await page.waitForURL("**/chat**");
		await beat(page, 1200);

		// If no workspace default model is set, pick the first available one.
		const modelPicker = page.getByRole("button", { name: "Select model" });
		if (await modelPicker.isVisible().catch(() => false)) {
			await modelPicker.click();
			const modelDialog = page.getByRole("dialog");
			await modelDialog.getByRole("button").first().click();
			await beat(page, 500);
		}

		const composer = page.locator('textarea[name="message"]');
		await cursorClick(page, composer);
		await composer.pressSequentially(
			"What is Workers KV? Search the docs and answer in two sentences.",
			{ delay: paced(25) },
		);
		await beat(page, 500);
		await composer.press("Enter");

		// The agent streams, calls the fetch tool (chain-of-thought shows
		// "Working…" → "Worked"), then writes its answer.
		const done = page
			.getByText("Worked", { exact: true })
			.or(page.getByRole("button", { name: "Retry" }));
		await expect(done.first()).toBeVisible({ timeout: 240_000 });
		await beat(page, 5000);
	});

	await test.step("human in the loop", async () => {
		await titleCard(page, {
			index: 4,
			total: 8,
			eyebrow: "// HUMAN IN THE LOOP",
			title: "You stay in control",
			sub: "Flip a tool to “Needs approval” and the agent waits for a human.",
		});
		// Back to the Research Assistant's editor to tighten one tool.
		await page.goto(agentUrl);
		await beat(page, 1600);
		await cursorClick(page, page.getByRole("button", { name: "Edit", exact: true }));
		await beat(page, 1000);

		// Expand the server card — tool rows (and their toggles) are collapsed.
		await cursorClick(page, page.getByRole("button", { name: "Expand" }).first());
		await beat(page, 900);

		// Each tool row carries a three-state toggle (allow / approval / off).
		await cursorClick(page, page.getByRole("button", { name: "Needs approval" }).first());
		await beat(page, 1000);
		await cursorClick(page, page.getByRole("button", { name: "Save changes" }));
		await beat(page, 1600);

		await cursorClick(page, page.getByRole("button", { name: "Test in chat" }));
		await page.waitForURL("**/chat**");
		await beat(page, 1000);

		const composer = page.locator('textarea[name="message"]');
		await cursorClick(page, composer);
		await composer.pressSequentially("What are Durable Objects? Search the docs.", {
			delay: paced(25),
		});
		await beat(page, 400);
		await composer.press("Enter");

		// The tool call now pauses on an approval card instead of running.
		const approve = page.getByRole("button", { name: "Approve" }).first();
		await expect(approve).toBeVisible({ timeout: 240_000 });
		await beat(page, 2200);
		await cursorClick(page, approve);

		const done = page
			.getByText("Worked", { exact: true })
			.or(page.getByRole("button", { name: "Retry" }));
		await expect(done.first()).toBeVisible({ timeout: 240_000 });
		await beat(page, 4000);
	});

	await test.step("share the agent", async () => {
		await titleCard(page, {
			index: 5,
			total: 8,
			eyebrow: "// SHARING",
			title: "Share your agents",
			sub: "Give a teammate — or a whole team — access, from member to admin.",
		});
		// Back on the Research Assistant, in its Permissions tab.
		await page.goto(agentUrl);
		await beat(page, 1400);
		await cursorClick(page, page.getByRole("button", { name: "Permissions", exact: true }));
		await beat(page, 1000);

		// People: pick a teammate and raise their access to Editor.
		await humanType(page, 'input[placeholder*="Search users"]', "alice");
		await beat(page, 800);
		await cursorClick(page, page.getByRole("button", { name: /Alice/ }));
		await beat(page, 900);
		await cursorClick(page, page.getByRole("button", { name: "Member", exact: true }));
		await beat(page, 600);
		await cursorClick(page, page.getByRole("menuitem", { name: "Editor" }));
		await beat(page, 900);

		// Teams: grant whole teams member access with one click each.
		await cursorClick(page, page.getByRole("button", { name: "Teams", exact: true }));
		await beat(page, 900);
		await cursorClick(page, page.getByRole("button", { name: "Data", exact: true }));
		await beat(page, 500);
		await cursorClick(page, page.getByRole("button", { name: "Marketing", exact: true }));
		await beat(page, 800);

		await cursorClick(page, page.getByRole("button", { name: "Save permissions" }));
		// The button disappears once the saved snapshot matches the draft.
		await expect(page.getByRole("button", { name: "Save permissions" })).toBeHidden({
			timeout: 15_000,
		});
		await beat(page, 1600);
	});

	await test.step("run code in a sandbox", async () => {
		await titleCard(page, {
			index: 6,
			total: 8,
			eyebrow: "// CODE EXECUTION",
			title: "Run real code",
			sub: "Give an agent a sandbox and it executes Python instead of guessing.",
		});
		// The seeded Python Developer is bound to a workspace sandbox.
		const analystId = await agentIdByName(WALKTHROUGH.analystAgentName);
		await page.goto(`/agents/${analystId}/chat`);
		await beat(page, 1400);

		const composer = page.locator('textarea[name="message"]');
		await cursorClick(page, composer);
		await composer.pressSequentially(
			"What day of the week was January 1st, 2000? Run Python to check.",
			{ delay: paced(25) },
		);
		await beat(page, 500);
		await composer.press("Enter");

		// The chain-of-thought shows "Create sandbox" then "Execute" steps
		// while the code runs, then the streamed answer.
		const done = page
			.getByText("Worked", { exact: true })
			.or(page.getByRole("button", { name: "Retry" }));
		await expect(done.first()).toBeVisible({ timeout: 240_000 });
		await beat(page, 5000);
	});

	await test.step("schedule a trigger", async () => {
		await titleCard(page, {
			index: 7,
			total: 8,
			eyebrow: "// TRIGGERS",
			title: "Put it on a schedule",
			sub: "Agents that run by themselves — cron and timezone aware.",
		});
		await cursorClick(page, page.getByRole("link", { name: "Triggers" }));
		await page.waitForURL("**/triggers");
		await beat(page, 1500);

		// Two "New trigger" buttons can coexist (top bar + empty state).
		await cursorClick(page, page.getByRole("button", { name: "New trigger" }).first());
		await page.waitForURL("**/triggers/new");
		await beat(page, 900);

		await humanType(
			page,
			'input[placeholder="What does this trigger do?"]',
			WALKTHROUGH.triggerName,
		);
		await beat(page, 400);

		await cursorClick(page, page.getByRole("button", { name: "Select an agent" }));
		const agentDialog = page.getByRole("dialog");
		await expect(agentDialog).toBeVisible();
		await beat(page, 800);
		await cursorClick(page, agentDialog.getByText(WALKTHROUGH.scoutAgentName));
		await beat(page, 600);

		const instructions = page.getByPlaceholder(/message sent to the agent on every run/);
		await cursorClick(page, instructions);
		await instructions.pressSequentially(
			"Search the Hugging Face Hub for this week's trending models and write a short digest of the top 3, with links.",
			{ delay: paced(12) },
		);
		await beat(page, 500);

		// Default schedule is daily at 09:00 — nudge the time so the schedule
		// interaction (and the refreshed "Next runs" preview) is on camera.
		await page.locator('input[type="time"]').fill("08:00");
		await expect(page.getByText("Next runs")).toBeVisible();
		// Let the debounced preview fetch land and render the next 3 runs.
		await beat(page, 2200);

		await cursorClick(page, page.getByRole("button", { name: "Create trigger" }));
		await page.waitForURL(/\/triggers\/[0-9a-f-]{36}$/, { timeout: 30_000 });
		// Detail page: Run now, Active switch, next-run time.
		await beat(page, 2600);
	});

	await test.step("call an agent over HTTP", async () => {
		await titleCard(page, {
			index: 8,
			total: 8,
			eyebrow: "// HTTP API",
			title: "Call agents from anywhere",
			sub: "Two requests and a token — n8n, scripts, your own apps.",
		});
		// The terminal types the curl call while the REAL request runs against
		// the seeded Docs Researcher; its actual reply is printed as the body.
		const question = "What is LangGraph? One sentence, based on the docs.";
		await apiScene(page, {
			command: [
				"curl -sS -X POST $AUXILIA_URL/threads/$THREAD_ID/runs/invoke \\",
				'  -H "Authorization: Bearer $AUXILIA_PAT" \\',
				`  -d '{"input": {"messages": [{"type": "human",`,
				`       "content": "${question}"}]}}'`,
			],
			run: async () => {
				const docsAgentId = await agentIdByName(WALKTHROUGH.docsAgentName);
				// Threads don't inherit the workspace default model — resolve it.
				const models = await api<{ id: string; isDefault: boolean }[]>(
					"GET",
					"/model-providers/models",
				);
				const modelId = (models?.find((m) => m.isDefault) ?? models?.[0])?.id;
				if (!modelId) throw new Error("no model available for the API scene");
				// A transient run error would sink a long take — retry the invoke
				// on a fresh thread a couple of times before giving up. Threads
				// are deleted afterwards either way so repeated recordings don't
				// accumulate orphaned API threads.
				let lastError: unknown;
				for (let attempt = 0; attempt < 3; attempt++) {
					const threadId = crypto.randomUUID();
					await api("POST", "/threads/", {
						id: threadId,
						agent_id: docsAgentId,
						model_id: modelId,
					});
					try {
						const result = await api<{ content: string }>(
							"POST",
							`/threads/${threadId}/runs/invoke`,
							{ input: { messages: [{ type: "human", content: question }] } },
						);
						return result?.content ?? "";
					} catch (error) {
						lastError = error;
					} finally {
						await api("DELETE", `/threads/${threadId}`).catch(() => {});
					}
				}
				throw lastError;
			},
		});
	});

	await test.step("close card", async () => {
		await brandCard(page, {
			tagline: TAGLINE,
			footer: "github.com/keurcien/auxilia",
			holdMs: 2800,
			leaveUp: true,
		});
	});

	await test.step("save the recording", async () => {
		const video = page.video();
		await page.close();
		if (video) {
			fs.mkdirSync(path.dirname(OUTPUT), { recursive: true });
			await video.saveAs(OUTPUT);
			console.log(`\nDemo video saved to ${OUTPUT}`);
			// -ss 0.3 trims the pre-first-paint blank so the file's first frame
			// (the poster on GitHub) is the logo cover, not a white screen.
			console.log("Convert to mp4 with: ffmpeg -ss 0.3 -i demo-output/auxilia-demo.webm -c:v libx264 -pix_fmt yuv420p demo-output/auxilia-demo.mp4");
		}
	});
});
