import { expect, test, type Page } from "@playwright/test";
import { api, authenticate, waitForTurn, WALKTHROUGH } from "../utils/demo";
import { docShot } from "../utils/docshot";

/**
 * Captures screenshots for the Nextra docs (docs/public/screenshots/).
 *
 * Prerequisites: a running backend and a production frontend
 * (npm run demo:web → :3100) seeded with `npm run demo:seed`, AND a recorded
 * walkthrough (`npm run demo:video`): several shots feature what it leaves
 * behind — the Research Assistant with its skill and its "Needs approval"
 * tool, the docs-brief skill, the Daily model digest trigger. The agent
 * shots fall back to a seeded agent; the skill, trigger and approval-card
 * shots cannot, and fail fast with a message saying so.
 *
 * Run: npm run docs:screenshots
 * Embed in MDX from the CDN the PNGs are uploaded to:
 *   ![Agents](https://pub-….r2.dev/docs/agents.png)
 */

interface Row {
	id: string;
	name: string;
}

/**
 * A named resource. Agents fall back to the first one of their kind (a
 * seeded agent is a fine subject for the agent shots); skills and triggers
 * are strict — an unrelated one would silently become "the" skill-detail
 * shot. Either way a miss FAILS the run (not a skip): a green suite must
 * mean every PNG the docs embed was actually written. `createdBy` names the
 * command that produces the resource.
 */
async function firstNamed(
	path: string,
	preferred: string,
	kind: string,
	{ createdBy = "npm run demo:seed", fallback = true } = {},
): Promise<Row> {
	const rows = (await api<Row[]>("GET", path)) ?? [];
	const row = rows.find((r) => r.name === preferred) ?? (fallback ? rows[0] : undefined);
	if (!row) {
		throw new Error(
			`${kind} "${preferred}" not found${fallback ? ` (and no other ${kind})` : ""} — run \`${createdBy}\` first`,
		);
	}
	return row;
}

const seededAgent = () => firstNamed("/agents/", "Docs Researcher", "agent");
/** The walkthrough's agent: a skill enabled and one tool on "Needs approval". */
const walkthroughAgent = () => firstNamed("/agents/", WALKTHROUGH.agentName, "agent");
const walkthroughSkill = () =>
	firstNamed("/skills/", WALKTHROUGH.skillName, "skill", {
		createdBy: "npm run demo:video",
		fallback: false,
	});
const walkthroughTrigger = () =>
	firstNamed("/triggers/", WALKTHROUGH.triggerName, "trigger", {
		createdBy: "npm run demo:video",
		fallback: false,
	});

interface AgentDetail {
	mcp_servers: { tools: Record<string, string> | null }[];
}

/**
 * The approval-card shot needs a tool that pauses. Only the walkthrough sets
 * one ("Needs approval" on the Research Assistant); a seeded agent never
 * pauses and the shot would wait its whole budget for a card that never
 * comes. Check the tool map first and fail with the real cause.
 */
async function agentWithApprovalTool(): Promise<Row> {
	const agent = await walkthroughAgent();
	const detail = await api<AgentDetail>("GET", `/agents/${agent.id}`);
	const gated = detail?.mcp_servers.some((binding) =>
		Object.values(binding.tools ?? {}).includes("needs_approval"),
	);
	if (!gated) {
		throw new Error(
			`agent "${agent.name}" has no tool on "Needs approval" — record the walkthrough (npm run demo:video) first`,
		);
	}
	return agent;
}

async function openEditor(page: Page, agentId: string): Promise<void> {
	await page.goto(`/agents/${agentId}`);
	await page.getByRole("button", { name: "Edit", exact: true }).click();
	await expect(page.getByRole("button", { name: "Add tool" })).toBeVisible();
}

/**
 * Type a message and send it. Typed, not `fill`ed: the composer is a
 * controlled input and a `fill` + Enter can race React's state update, so
 * the Enter lands on an empty draft and nothing is sent.
 */
async function sendMessage(page: Page, message: string): Promise<void> {
	const composer = page.locator('textarea[name="message"]');
	await composer.click();
	await composer.pressSequentially(message, { delay: 5 });
	await expect(composer).toHaveValue(message);
	await composer.press("Enter");
}

/** Send a message and wait for the turn to finish (tool calls included). */
async function chatAndWait(page: Page, agentId: string, message: string): Promise<void> {
	await page.goto(`/agents/${agentId}/chat`);
	await sendMessage(page, message);
	await waitForTurn(page, 180_000);
	await page.waitForTimeout(800);
}

test.describe("docs screenshots", () => {
	test("sign-in page", async ({ page }) => {
		await page.emulateMedia({ colorScheme: "light", reducedMotion: "reduce" });
		await page.goto("/auth");
		await expect(page.locator("#email")).toBeVisible();
		await docShot(page, "auth");
	});

	test.describe("authenticated pages", () => {
		test.beforeEach(async ({ context, page, baseURL }) => {
			await authenticate(context, baseURL!);
			await page.emulateMedia({ colorScheme: "light", reducedMotion: "reduce" });
		});

		/* ---------------------------- agents ---------------------------- */

		test("agents list", async ({ page }) => {
			await page.goto("/agents");
			await expect(page.getByRole("button", { name: "New agent" })).toBeVisible();
			await docShot(page, "agents");
		});

		test("agent detail", async ({ page }) => {
			const agent = await walkthroughAgent();
			await page.goto(`/agents/${agent.id}`);
			await expect(page.getByRole("button", { name: "Test in chat" })).toBeVisible();
			await docShot(page, "agent-detail");
		});

		test("agent editor", async ({ page }) => {
			const agent = await walkthroughAgent();
			await openEditor(page, agent.id);
			await docShot(page, "agent-editor");
		});

		test("agent tool settings", async ({ page }) => {
			const agent = await walkthroughAgent();
			await openEditor(page, agent.id);
			// Server cards are collapsed; the tool rows carry the three-state toggles.
			await page.getByRole("button", { name: "Expand" }).first().click();
			await expect(page.getByRole("button", { name: "Needs approval" }).first()).toBeVisible();
			await docShot(page, "agent-tool-settings");
		});

		test("agent add-tool dialog", async ({ page }) => {
			const agent = await walkthroughAgent();
			await openEditor(page, agent.id);
			await page.getByRole("button", { name: "Add tool" }).click();
			await expect(page.getByRole("dialog")).toBeVisible();
			await docShot(page, "agent-add-tool-dialog");
		});

		test("agent add-skill dialog", async ({ page }) => {
			const agent = await walkthroughAgent();
			await openEditor(page, agent.id);
			await page.getByRole("button", { name: "Add skill" }).click();
			await expect(page.getByRole("dialog")).toBeVisible();
			await docShot(page, "agent-skills");
		});

		test("agent permissions", async ({ page }) => {
			const agent = await walkthroughAgent();
			await page.goto(`/agents/${agent.id}`);
			await page.getByRole("button", { name: "Permissions", exact: true }).click();
			await expect(page.getByRole("button", { name: "Teams", exact: true })).toBeVisible();
			await docShot(page, "agent-permissions");
		});

		/* ----------------------------- chat ----------------------------- */

		test("chat starter", async ({ page }) => {
			const agent = await seededAgent();
			await page.goto(`/agents/${agent.id}/chat`);
			await expect(page.locator('textarea[name="message"]')).toBeVisible();
			await docShot(page, "chat");
		});

		test("chat with a tool call", async ({ page }) => {
			test.setTimeout(240_000);
			const agent = await seededAgent();
			await chatAndWait(
				page,
				agent.id,
				"How do I define a computed signal in Angular? Look it up in the docs and answer in three sentences.",
			);
			// Expand the "Worked" steps so the tool call is on screen.
			const trigger = page.getByText("Worked", { exact: true }).first().locator("xpath=ancestor::button[1]");
			if ((await trigger.getAttribute("aria-expanded")) !== "true") await trigger.click();
			await page.waitForTimeout(600);
			await docShot(page, "chat-tool-call");
		});

		test("chat approval card", async ({ page }) => {
			// Two live runs may queue behind each other on the worker — give
			// this one real headroom; the timeout only catches a wedged run.
			test.setTimeout(480_000);
			// The walkthrough leaves one of the Research Assistant's tools on
			// "Needs approval" — the run pauses on the approval card.
			const agent = await agentWithApprovalTool();
			await page.goto(`/agents/${agent.id}/chat`);
			await sendMessage(page, "What are Cloudflare Workers? Search the docs before answering.");
			await expect(page.getByRole("button", { name: "Approve" }).first()).toBeVisible({
				timeout: 420_000,
			});
			await page.waitForTimeout(800);
			await docShot(page, "chat-approval");
		});

		/* -------------------------- MCP servers ------------------------- */

		test("mcp servers list", async ({ page }) => {
			await page.goto("/mcp-servers");
			await expect(page.getByRole("button", { name: "Add MCP server" })).toBeVisible();
			await docShot(page, "mcp-servers");
		});

		test("mcp server catalog", async ({ page }) => {
			await page.goto("/mcp-servers/add");
			await expect(page.getByPlaceholder("Search the catalog…")).toBeVisible();
			await docShot(page, "mcp-server-catalog");
		});

		test("mcp server custom form", async ({ page }) => {
			await page.goto("/mcp-servers/add/custom");
			await page.locator("#mcp-url").fill("https://mcp.example.com/mcp");
			await page.locator("#mcp-name").fill("Internal warehouse");
			await docShot(page, "mcp-server-custom");
		});

		/* ----------------------------- skills --------------------------- */

		test("skills library", async ({ page }) => {
			await page.goto("/skills");
			await expect(page.getByRole("button", { name: "New skill" })).toBeVisible();
			await docShot(page, "skills-library");
		});

		test("skill detail", async ({ page }) => {
			const skill = await walkthroughSkill();
			await page.goto(`/skills/${skill.id}`);
			await expect(page.getByText("INSTRUCTIONS", { exact: true })).toBeVisible();
			await docShot(page, "skill-detail");
		});

		test("skill editor (new)", async ({ page }) => {
			await page.goto("/skills/new");
			await page.locator('input[placeholder="skill-name"]').fill("release-notes");
			await page
				.locator('input[placeholder^="What the skill does"]')
				.fill("Turns a list of merged pull requests into customer-facing release notes. Use when asked for release notes or a changelog.");
			await page.getByPlaceholder(/The procedure the agent follows/).fill(
				[
					"# When to use",
					"The user asks for release notes, a changelog or a \"what shipped\" summary.",
					"",
					"# Steps",
					"1. List the merged pull requests for the period with your GitHub tools.",
					"2. Group them: New, Improved, Fixed. Drop internal-only changes.",
					"3. One line per item, written for customers — what it lets them do, not how.",
					"4. End with a `Full changelog` link to the compare view.",
				].join("\n"),
			);
			await docShot(page, "skill-new");
		});

		test("skill sources", async ({ page }) => {
			await page.goto("/skills?view=sources");
			await expect(page.getByRole("button", { name: "Connect repository" })).toBeVisible();
			await docShot(page, "skills-sources");
		});

		test("skill source form", async ({ page }) => {
			test.setTimeout(120_000);
			await page.goto("/skills/sources/new");
			// A small public repository in the Agent Skills layout (skills at the
			// root, no symlinks, under the 10 MB archive cap) whose skill names
			// are not in this library — the preview then lists real imports
			// rather than a page of name-collision warnings.
			await page
				.locator('input[placeholder="https://github.com/acme/skills"]')
				.fill("https://github.com/cloudflare/skills");
			// The preview lists the skills the repository holds (public repo, no token).
			await page.getByRole("button", { name: "Preview", exact: true }).click();
			// The preview header shows the resolved revision ("@ abc1234") once
			// the repository has been read — the skill list is on screen then.
			const revision = page.getByText(/^@ [0-9a-f]{6,}/);
			await expect(revision).toBeVisible({ timeout: 60_000 });
			// The results render below the fold — bring the header ("N skills
			// found @ revision") and the first entries on screen.
			await revision.scrollIntoViewIfNeeded();
			await page.mouse.wheel(0, 240);
			await page.waitForTimeout(800);
			await docShot(page, "skill-source-new");
		});

		/* ---------------------------- triggers -------------------------- */

		test("triggers list", async ({ page }) => {
			await page.goto("/triggers");
			await expect(page.getByRole("button", { name: "New trigger" }).first()).toBeVisible();
			await docShot(page, "triggers");
		});

		test("trigger detail", async ({ page }) => {
			const trigger = await walkthroughTrigger();
			await page.goto(`/triggers/${trigger.id}`);
			await expect(page.getByRole("button", { name: "Run now" })).toBeVisible();
			await docShot(page, "trigger-detail");
		});

		test("trigger editor (new)", async ({ page }) => {
			const agent = await seededAgent();
			await page.goto("/triggers/new");
			await page.locator('input[placeholder="What does this trigger do?"]').fill("Weekly docs digest");
			await page.getByRole("button", { name: "Select an agent" }).click();
			const dialog = page.getByRole("dialog");
			await expect(dialog).toBeVisible();
			await dialog.getByText(agent.name).click();
			await page
				.getByPlaceholder(/message sent to the agent on every run/)
				.fill("Summarize what changed in the LangGraph docs this week and list the three most useful new pages, with links.");
			await page.locator('input[type="time"]').fill("08:00");
			await expect(page.getByText("Next runs")).toBeVisible();
			await page.waitForTimeout(2000);
			await docShot(page, "trigger-new");
		});

		/* ---------------------------- settings -------------------------- */

		test("settings — access tokens", async ({ page }) => {
			await page.goto("/settings");
			await page.getByRole("button", { name: "Access tokens" }).click();
			await docShot(page, "settings-tokens");
		});

		test("settings — models", async ({ page }) => {
			await page.goto("/settings");
			await page.getByRole("button", { name: "Models" }).click();
			await docShot(page, "settings-models");
		});

		test("settings — sandboxes", async ({ page }) => {
			await page.goto("/settings");
			await page.getByRole("button", { name: "Sandboxes" }).click();
			await expect(page.getByRole("button", { name: "Add sandbox" })).toBeVisible();
			await docShot(page, "settings-sandboxes");
		});

		test("sandbox dialog — OpenSandbox", async ({ page }) => {
			await page.goto("/settings");
			await page.getByRole("button", { name: "Sandboxes" }).click();
			await page.getByRole("button", { name: "Add sandbox" }).click();
			const dialog = page.getByRole("dialog");
			await expect(dialog).toBeVisible();
			await dialog.locator("#sandbox-name").fill("Data lab");
			await dialog.locator("#sandbox-description").fill("Python runtime for the analysts' agents");
			await dialog.locator("#sandbox-url").fill("sandbox.internal.example.com");
			await dialog.locator("#sandbox-secret").fill("osb_live_2f9c…");
			await dialog.locator("#sandbox-packages").fill("pandas, gspread, google-auth");
			await dialog.locator("#sandbox-image").fill("ghcr.io/acme/agent-runtime:1.4.0");
			await dialog.locator("#sandbox-volumes").fill("/srv/auxilia/secrets:/secrets:ro");
			await docShot(page, "sandbox-dialog-opensandbox");
		});

		test("sandbox dialog — Daytona", async ({ page }) => {
			await page.goto("/settings");
			await page.getByRole("button", { name: "Sandboxes" }).click();
			await page.getByRole("button", { name: "Add sandbox" }).click();
			const dialog = page.getByRole("dialog");
			await expect(dialog).toBeVisible();
			await dialog.getByRole("button", { name: "Daytona" }).click();
			await dialog.locator("#sandbox-name").fill("Daytona runtime");
			await dialog.locator("#sandbox-secret").fill("dtn_…");
			await dialog.locator("#sandbox-packages").fill("python-pptx, matplotlib");
			await dialog.locator("#sandbox-snapshot").fill("acme/deck-runtime:1.0");
			await docShot(page, "sandbox-dialog-daytona");
		});

		/* ------------------------------ users --------------------------- */

		test("users and teams", async ({ page }) => {
			await page.goto("/users");
			await page.waitForLoadState("networkidle").catch(() => {});
			await docShot(page, "users");
		});
	});
});
