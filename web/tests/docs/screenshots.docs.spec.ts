import { expect, test } from "@playwright/test";
import { api, authenticate } from "../utils/demo";
import { docShot } from "../utils/docshot";

/**
 * Captures screenshots for the Nextra docs (docs/public/screenshots/).
 *
 * Prerequisites: a running backend and a production frontend
 * (npm run demo:web → :3100) seeded with `npm run demo:seed`.
 *
 * Run: npm run docs:screenshots
 * Embed in MDX as: ![Agents](/screenshots/agents.png)
 */

interface AgentRow {
	id: string;
	name: string;
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

		test("agents list", async ({ page }) => {
			await page.goto("/agents");
			await expect(page.getByRole("button", { name: "New agent" })).toBeVisible();
			await docShot(page, "agents");
		});

		test("agent detail", async ({ page }) => {
			const agents = (await api<AgentRow[]>("GET", "/agents/")) ?? [];
			const agent = agents.find((a) => a.name === "Docs Researcher") ?? agents[0];
			test.skip(!agent, "no seeded agent found — run `npm run demo:seed` first");
			await page.goto(`/agents/${agent.id}`);
			await expect(page.getByRole("button", { name: "Test in chat" })).toBeVisible();
			await docShot(page, "agent-detail");
		});

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

		test("chat starter", async ({ page }) => {
			const agents = (await api<AgentRow[]>("GET", "/agents/")) ?? [];
			const agent = agents.find((a) => a.name === "Docs Researcher") ?? agents[0];
			test.skip(!agent, "no seeded agent found — run `npm run demo:seed` first");
			await page.goto(`/agents/${agent.id}/chat`);
			await expect(page.locator('textarea[name="message"]')).toBeVisible();
			await docShot(page, "chat");
		});
	});
});
