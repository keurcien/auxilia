import { expect, test, type FrameLocator, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import {
	agentIdByName,
	api,
	authenticate,
	beat,
	brandCard,
	cursorClick,
	paced,
	titleCard,
} from "../utils/demo";

/**
 * Records the Shopping assistant demo as a video — a companion to
 * walkthrough.demo.spec.ts focused on one agent bound to the Choose Shop MCP
 * server (an MCP App: tool results render as an interactive carousel in a
 * sandboxed iframe inside the conversation).
 *
 * Storyline: the product demo's intro card → a title slide about the
 * Shopping assistant, opening on its starter screen (the session is
 * authenticated with a cookie: no sign-in or agent picking on camera) →
 * part 1 "Entrée par les ventes" (ask for live sales,
 * open the first sale from the carousel, add a product to the cart, go back)
 * → part 2 "Entrée par les produits" (describe a gift, one product search,
 * open a product sheet, add it to the cart) → close card.
 *
 * Prerequisites: a running backend, a production frontend (npm run demo:web →
 * :3100), the demo admin (DEMO_EMAIL / DEMO_PASSWORD) and an agent named
 * `DEMO_SHOPPING_AGENT` (default "Shopping assistant") bound to the Choose
 * Shop MCP server, with its tools synced. The Choose Shop tools drill down
 * by calling the server from inside the app (search_products / get_product),
 * so none of them may be disabled for the agent.
 *
 * Run: npm run demo:video:shopping
 * Output: web/demo-output/auxilia-shopping-demo.webm
 */

const OUTPUT = path.join(
	process.cwd(),
	"demo-output",
	"auxilia-shopping-demo.webm",
);

const TAGLINE = "The open-source MCP client for teams";
const AGENT_NAME = process.env.DEMO_SHOPPING_AGENT ?? "Shopping assistant";
/**
 * Display name of the model to chat with, picked in the composer on camera
 * unless it is already the workspace default. Reasoning effort is picked the
 * same way (`DEMO_REASONING_EFFORT` is the menu label; "" keeps the default).
 *
 * Why DeepSeek V4 Pro with thinking Off: trials on the gift prompt (which
 * should trigger exactly one search — every extra call is another carousel):
 *   DeepSeek V4 Pro, Off      1·1·1·4·3 calls, 8–16 s   ← used
 *   DeepSeek V4 Pro, default  3·1·4
 *   DeepSeek V4 Flash, default 2·2·4 (and 5·5·4·4·5 on camera)
 *   DeepSeek V4 Flash, Off    14·31·51 (!)
 *   GPT-4o mini 1·1·1 · Haiku 4.5 2 · Sonnet 4.6 4 · Sonnet 5 5 · Gemini 3 Flash 10
 * The single-search check + retries below cover the remaining takes.
 */
const MODEL_NAME = process.env.DEMO_MODEL_NAME ?? "DeepSeek V4 Pro";
const REASONING_EFFORT = process.env.DEMO_REASONING_EFFORT ?? "Off";
/** Re-record when the gift prompt triggered more than one tool call (default on). */
const SINGLE_SEARCH = (process.env.DEMO_SINGLE_SEARCH ?? "1") !== "0";

/**
 * Part 1 prompt. The original storyline asked for men's clothing ("y a des
 * ventes de vêtements pour homme en ce moment ?") but search_sales matches
 * free text against the sale taxonomy, and on 2026-09-06 no live sale
 * mentioned "homme" (0 of 120) — the carousel came back empty unless the
 * model dropped the word. "mode" matches the Mode section whichever filter
 * the model picks. Override with DEMO_SALES_PROMPT when men's sales are live.
 */
const SALES_PROMPT =
	process.env.DEMO_SALES_PROMPT ??
	"y a des ventes de mode homme en ce moment ?";
const GIFT_PROMPT =
	process.env.DEMO_GIFT_PROMPT ??
	"Je cherche un cadeau pour la fille de 3 ans d'un ami, avec un budget max de 40€. Plutôt ludique.";

/** The Choose carousel lives two iframes deep: /sandbox.html → blob: app page. */
const appFrame = (page: Page): FrameLocator =>
	page
		.frameLocator('iframe[src*="sandbox.html"]')
		.last()
		.frameLocator("#mcp-app-frame");

/** Scroll the (last) MCP-app widget to the middle of the conversation pane. */
async function revealWidget(page: Page): Promise<void> {
	const widget = page.locator('iframe[src*="sandbox.html"]').last();
	await widget.evaluate((el) => {
		el.scrollIntoView({ block: "center", behavior: "smooth" });
	});
	await beat(page, 900);
}

/** Pick the demo model in the composer if the starter page defaulted to another one. */
async function ensureModel(page: Page): Promise<void> {
	const composer = page.locator('form:has(textarea[name="message"])');
	if (
		await composer
			.getByRole("button", { name: MODEL_NAME })
			.isVisible()
			.catch(() => false)
	) {
		return;
	}
	const pill = composer
		.getByRole("button")
		.filter({
			hasText: /Select model|GPT|Claude|Gemini|DeepSeek|GLM|MiMo|Muse/,
		})
		.first();
	await cursorClick(page, pill);
	const dialog = page.getByRole("dialog");
	await dialog.getByPlaceholder("Search models...").fill(MODEL_NAME);
	await cursorClick(page, dialog.getByRole("button", { name: MODEL_NAME }));
	await expect(dialog).toBeHidden();
	await beat(page, 400);
}

/** Pick the reasoning-effort level in the composer's brain menu (skipped when empty). */
async function ensureEffort(page: Page): Promise<void> {
	if (!REASONING_EFFORT) return;
	const composer = page.locator('form:has(textarea[name="message"])');
	const pill = composer
		.getByRole("button")
		.filter({
			hasText: /^(Auto|Default|Off|Minimal|Low|Medium|High|Extra high|Max)/,
		})
		.first();
	if ((await pill.innerText().catch(() => "")).trim() === REASONING_EFFORT)
		return;
	await cursorClick(page, pill);
	const item = page
		.getByRole("menuitem", { name: REASONING_EFFORT, exact: true })
		.or(page.getByText(REASONING_EFFORT, { exact: true }))
		.first();
	await cursorClick(page, item);
	await beat(page, 400);
}

/** Type the prompt into the starter composer, send it, and wait for the reply to finish. */
async function ask(page: Page, prompt: string): Promise<void> {
	const composer = page.locator('textarea[name="message"]');
	await expect(composer).toBeEnabled({ timeout: 30_000 });
	await cursorClick(page, composer);
	await composer.pressSequentially(prompt, { delay: paced(25) });
	await beat(page, 600);
	await composer.press("Enter");
	await page.waitForURL(/\/chat\/[0-9a-f-]{36}$/, { timeout: 30_000 });
	const done = page.getByRole("button", { name: "Retry" });
	await expect(done.first()).toBeVisible({ timeout: 240_000 });
}

/** Product cards with a real price (out-of-stock items show "—" and no amount). */
const pricedProduct = (app: FrameLocator) =>
	app.locator(".card[data-kind=product]:has(span.price:not([style]))").first();

/** Delete the demo user's earlier threads on this agent so the sidebar starts clean. */
async function resetShoppingThreads(agentId: string): Promise<void> {
	const page = await api<{ items: { id: string; agent_id: string }[] }>(
		"GET",
		"/threads/?limit=200",
	);
	for (const thread of page?.items ?? []) {
		if (thread.agent_id === agentId) {
			await api("DELETE", `/threads/${thread.id}`).catch(() => {});
		}
	}
}

let agentId = "";

// A model can still pick a filter that matches nothing (an empty carousel is
// not a demo). The spec asserts on the carousel content, and a retry re-records
// the whole video from scratch — Playwright discards the failed attempt's file.
test.describe.configure({ retries: Number(process.env.DEMO_RETRIES ?? 4) });

test.beforeEach(async () => {
	agentId = await agentIdByName(AGENT_NAME);
	await resetShoppingThreads(agentId);
});

test("shopping assistant demo", async ({ page, baseURL }) => {
	await page.emulateMedia({ colorScheme: "light" });
	await page
		.context()
		.addCookies([
			{
				name: "sidebar_state",
				value: "true",
				domain: new URL(baseURL!).hostname,
				path: "/",
			},
		]);

	const starterPath = `/agents/${agentId}/chat`;

	await test.step("intro card", async () => {
		// Open the starter screen already signed in, hidden behind a white
		// cover showing the logo row at the brand card's exact spot, so the
		// video's first frame is the brand card and the page never blinks.
		await authenticate(page.context(), baseURL!);
		const rowUri = `data:image/png;base64,${fs
			.readFileSync(
				path.join(process.cwd(), "tests", "demo", "assets", "brand-row.png"),
			)
			.toString("base64")}`;
		const coverStyle =
			'<style id="__demo_cover">html::before{content:"";position:fixed;' +
			`inset:0;z-index:2147483646;background:#fff url("${rowUri}") ` +
			"567px 384px / 306px 76px no-repeat;}</style>";
		await page.route(
			(url) => url.pathname === starterPath,
			async (route) => {
				if (route.request().resourceType() !== "document")
					return route.continue();
				const response = await route.fetch();
				const body = (await response.text()).replace(
					"</head>",
					`${coverStyle}</head>`,
				);
				await route.fulfill({ response, body });
			},
		);
		await page.goto(starterPath);
		await page.unrouteAll();
		await expect(page.locator('textarea[name="message"]')).toBeVisible({
			timeout: 30_000,
		});
		await brandCard(page, { tagline: TAGLINE, holdMs: 2200, instant: true });
	});

	await test.step("shopping assistant slide", async () => {
		await beat(page, 900);
		await titleCard(page, {
			eyebrow: "// MCP APPS",
			title: "Shopping assistant",
			sub: "Un agent auxilia branché sur le serveur MCP de Choose — ventes, produits et panier s'affichent directement dans la conversation.",
		});
		await expect(page.getByRole("heading", { name: AGENT_NAME })).toBeVisible();
		await beat(page, 2200);
	});

	await test.step("part 1 — entrée par les ventes", async () => {
		await titleCard(page, {
			index: 1,
			total: 2,
			eyebrow: "// SHOPPING ASSISTANT",
			title: "Entrée par les ventes",
			sub: "Demandez ce qui est en vente : l'agent répond avec un carrousel interactif. Ouvrez une vente, ajoutez au panier — sans quitter la conversation.",
		});
		await ensureModel(page);
		await ensureEffort(page);
		await ask(page, SALES_PROMPT);

		const app = appFrame(page);
		const saleCards = app.locator(".card[data-kind=sale]");
		await expect(saleCards.first()).toBeVisible({ timeout: 60_000 });
		await beat(page, 1800);
		await revealWidget(page);
		await beat(page, 1400);

		// Drill into the first sale: the app calls search_products itself.
		await cursorClick(page, saleCards.first());
		const productCards = app.locator(".card[data-kind=product]");
		await expect(productCards.first()).toBeVisible({ timeout: 60_000 });
		await beat(page, 2400);

		const priced = pricedProduct(app);
		const product = (await priced.count()) > 0 ? priced : productCards.first();
		await cursorClick(page, product.locator("button[data-add]"));
		await expect(app.locator("#toast.show")).toBeVisible();
		await beat(page, 2400);

		await cursorClick(page, app.locator("#back"));
		await expect(saleCards.first()).toBeVisible();
		await beat(page, 2200);
	});

	await test.step("part 2 — entrée par les produits", async () => {
		await titleCard(page, {
			index: 2,
			total: 2,
			eyebrow: "// SHOPPING ASSISTANT",
			title: "Entrée par les produits",
			sub: "Décrivez le cadeau idéal : une recherche dans tout le catalogue, la fiche produit, et le panier.",
		});
		await cursorClick(page, page.getByRole("button", { name: "New thread" }));
		await page.waitForURL(/\/agents\/[0-9a-f-]{36}\/chat$/, {
			timeout: 30_000,
		});
		await beat(page, 1200);
		await ensureModel(page);
		await ensureEffort(page);
		await ask(page, GIFT_PROMPT);

		const widgets = await page.locator('iframe[src*="sandbox.html"]').count();
		if (SINGLE_SEARCH && widgets !== 1) {
			throw new Error(
				`gift prompt rendered ${widgets} carousels (expected exactly one search) — retrying the take`,
			);
		}

		const app = appFrame(page);
		const productCards = app.locator(".card[data-kind=product]");
		await expect(productCards.first()).toBeVisible({ timeout: 60_000 });
		await beat(page, 1800);
		await revealWidget(page);
		await beat(page, 1600);

		// Open the product sheet (the app calls get_product itself).
		const priced = pricedProduct(app);
		const product = (await priced.count()) > 0 ? priced : productCards.first();
		await cursorClick(page, product.locator("button.soft[data-drill]"));
		const addToCart = app.locator("#add");
		await expect(addToCart).toBeVisible({ timeout: 60_000 });
		await beat(page, 2400);

		const nextImage = app.locator(".gallery .nav.next");
		if (await nextImage.isVisible().catch(() => false)) {
			await cursorClick(page, nextImage);
			await beat(page, 1400);
		}

		await cursorClick(page, addToCart);
		await expect(app.locator("#toast.show")).toBeVisible();
		await beat(page, 2800);
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
			console.log(`\nShopping demo video saved to ${OUTPUT}`);
			console.log(
				"Convert to mp4 with: ffmpeg -ss 0.3 -i demo-output/auxilia-shopping-demo.webm -c:v libx264 -pix_fmt yuv420p demo-output/auxilia-shopping-demo.mp4",
			);
		}
	});
});
