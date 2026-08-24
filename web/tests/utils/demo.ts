import type { BrowserContext, Locator, Page } from "@playwright/test";

/**
 * Shared helpers for the demo video (tests/demo/) and the docs screenshot
 * suite (tests/docs/). Both expect a running backend and a production
 * frontend (npm run demo:web → :3100) seeded with `npm run demo:seed`.
 *
 * Env vars mirror scripts/seed-demo.mjs — keep the defaults in sync.
 */
export const BACKEND_URL = (process.env.BACKEND_URL ?? "http://localhost:8000").replace(
	/\/$/,
	"",
);
export const DEMO_EMAIL = process.env.DEMO_EMAIL ?? "demo@auxilia.dev";
export const DEMO_PASSWORD = process.env.DEMO_PASSWORD ?? "auxilia-demo-123";

/**
 * Pacing factor for the recorded UI walkthrough: 2 = beats, typing and
 * cursor glides run twice as fast. Title cards and the terminal scene keep
 * their own designed pace. Override with DEMO_SPEED=1 for the original feel.
 */
export const DEMO_SPEED = Math.max(0.5, Number(process.env.DEMO_SPEED) || 2);

/** Scale a duration by the walkthrough pacing factor. */
export const paced = (ms: number) => Math.round(ms / DEMO_SPEED);

/** Resources created on camera by the walkthrough (cleaned up before re-runs). */
export const WALKTHROUGH = {
	// Custom server added via the form. (Was Microsoft Learn, but its
	// streamable-HTTP GET stream flaps and wedges tool calls mid-recording.)
	serverName: "Cloudflare Docs",
	serverUrl: "https://docs.mcp.cloudflare.com/mcp",
	serverDescription: "Search the Cloudflare developer documentation.",
	serverIconUrl: "https://developers.cloudflare.com/favicon.png",
	// Official server installed with one click from the catalog.
	catalogServerName: "DeepWiki",
	catalogServerUrl: "https://mcp.deepwiki.com/mcp",
	// Agent built on camera.
	agentName: "Research Assistant",
	// Seeded agents featured in the code-execution, trigger and API scenes.
	analystAgentName: "Python Developer",
	scoutAgentName: "Model Scout",
	docsAgentName: "Docs Researcher",
	// Trigger created on camera.
	triggerName: "Daily model digest",
};

let cachedToken: string | undefined;

/** Sign in against the backend directly and return a bearer JWT. */
export async function apiToken(): Promise<string> {
	if (cachedToken) return cachedToken;
	const res = await fetch(`${BACKEND_URL}/auth/signin`, {
		method: "POST",
		headers: { "content-type": "application/json" },
		body: JSON.stringify({ email: DEMO_EMAIL, password: DEMO_PASSWORD }),
	});
	if (!res.ok) {
		throw new Error(
			`signin failed (${res.status}) — did you run \`npm run demo:seed\` against ${BACKEND_URL}?`,
		);
	}
	const cookie = res.headers
		.getSetCookie()
		.find((c) => c.startsWith("access_token="));
	if (!cookie) throw new Error("signin response did not set an access_token cookie");
	cachedToken = cookie.split(";")[0].split("=").slice(1).join("=");
	return cachedToken;
}

export async function api<T = unknown>(
	method: string,
	path: string,
	body?: unknown,
): Promise<T | null> {
	const token = await apiToken();
	const res = await fetch(`${BACKEND_URL}${path}`, {
		method,
		headers: {
			"content-type": "application/json",
			authorization: `Bearer ${token}`,
		},
		body: body === undefined ? undefined : JSON.stringify(body),
	});
	if (!res.ok) throw new Error(`${method} ${path} → ${res.status} ${await res.text()}`);
	if (res.status === 204) return null;
	return (await res.json()) as T;
}

/** Authenticate a browser context by injecting the JWT cookie (no UI signin). */
export async function authenticate(context: BrowserContext, baseURL: string): Promise<void> {
	const token = await apiToken();
	const { hostname } = new URL(baseURL);
	await context.addCookies([
		{ name: "access_token", value: token, domain: hostname, path: "/" },
		// Keep the sidebar expanded for consistent framing.
		{ name: "sidebar_state", value: "true", domain: hostname, path: "/" },
	]);
}

/**
 * Delete the agent + MCP server the walkthrough creates on camera, so the
 * demo can be re-recorded (the MCP server URL has a unique constraint).
 */
export async function resetWalkthroughResources(): Promise<void> {
	const triggers = await api<{ id: string; name: string }[]>("GET", "/triggers/");
	for (const trigger of triggers ?? []) {
		if (trigger.name === WALKTHROUGH.triggerName) {
			await api("DELETE", `/triggers/${trigger.id}`);
		}
	}
	const agents = await api<{ id: string; name: string }[]>("GET", "/agents/");
	for (const agent of agents ?? []) {
		if (agent.name === WALKTHROUGH.agentName) {
			await api("DELETE", `/agents/${agent.id}/permanent`);
		}
	}
	const servers = await api<{ id: string; url: string }[]>("GET", "/mcp-servers/");
	for (const server of servers ?? []) {
		if (server.url === WALKTHROUGH.serverUrl || server.url === WALKTHROUGH.catalogServerUrl) {
			await api("DELETE", `/mcp-servers/${server.id}?detach_agents=true`);
		}
	}
}

/** Look up a seeded agent's id (for direct chat navigation in the demo). */
export async function agentIdByName(name: string): Promise<string> {
	const agents = await api<{ id: string; name: string }[]>("GET", "/agents/");
	const agent = agents?.find((a) => a.name === name);
	if (!agent) throw new Error(`agent "${name}" not found — run \`npm run demo:seed\` first`);
	return agent.id;
}

/**
 * Make sure the walkthrough agent's tool map is persisted. The editor seeds
 * it from a live list-tools call when the server card mounts; if the agent
 * was saved before that resolved, the binding has no tools and chat refuses
 * to start. sync-tools merges server-side, so calling it is always safe.
 */
export async function ensureWalkthroughAgentTools(agentUrl: string): Promise<void> {
	const agentId = agentUrl.match(/agents\/([0-9a-f-]{36})/)?.[1];
	if (!agentId) throw new Error(`could not extract agent id from ${agentUrl}`);
	const servers = await api<{ id: string; url: string }[]>("GET", "/mcp-servers/");
	const server = servers?.find((s) => s.url === WALKTHROUGH.serverUrl);
	if (!server) throw new Error(`walkthrough MCP server not found (${WALKTHROUGH.serverUrl})`);
	const binding = await api<{ tools: Record<string, string> | null }>(
		"POST",
		`/agents/${agentId}/mcp-servers/${server.id}/sync-tools`,
	);
	// sync-tools returns 200 with tools=null when the remote server is
	// unreachable — chat would then refuse to start with "not configured".
	if (!binding?.tools || Object.keys(binding.tools).length === 0) {
		throw new Error(
			`tool sync for ${WALKTHROUGH.serverName} returned no tools — is ${WALKTHROUGH.serverUrl} reachable from the backend?`,
		);
	}
}

/* ------------------------------------------------------------------ */
/* Title cards — full-screen interstitials injected into the recording  */
/* (Petrol Mono: Space Grotesk display, IBM Plex Mono eyebrows, petrol  */
/* #16606E accent on white — see design/README.md).                     */
/* ------------------------------------------------------------------ */

const CARD_CSS = `
	[data-demo-card] .dc-word {
		display: inline-block; opacity: 0; transform: translateY(26px);
		animation: dcRise 520ms cubic-bezier(0.16, 1, 0.3, 1) forwards;
	}
	@keyframes dcRise { to { opacity: 1; transform: translateY(0); } }
	[data-demo-card] .dc-bar {
		width: 0; animation: dcBar 560ms cubic-bezier(0.16, 1, 0.3, 1) 380ms forwards;
	}
	@keyframes dcBar { to { width: var(--dc-bar-w, 132px); } }
	[data-demo-card] .dc-fade {
		opacity: 0; animation: dcFade 480ms ease 560ms forwards;
	}
	@keyframes dcFade { to { opacity: 1; } }
`;

type CardInner = {
	css: string;
	html: string;
	holdMs: number;
	leaveUp: boolean;
	/** Mount fully opaque at once (intro) instead of fading in over the page. */
	instant?: boolean;
};

/** Mount a card overlay, play it, and (unless leaveUp) fade it away. */
async function playCard(page: Page, inner: CardInner): Promise<void> {
	await page.evaluate(async ({ css, html, holdMs, leaveUp, instant }) => {
		const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
		const host = document.createElement("div");
		host.setAttribute("data-demo-card", "");
		host.style.cssText =
			"position:fixed;inset:0;z-index:2147483647;background:#ffffff;" +
			"display:flex;align-items:center;justify-content:center;" +
			"opacity:0;transition:opacity 260ms ease;";
		const style = document.createElement("style");
		style.textContent = css;
		host.appendChild(style);
		const content = document.createElement("div");
		content.style.cssText =
			"display:flex;flex-direction:column;align-items:center;text-align:center;" +
			"max-width:920px;padding:0 48px;";
		document.body.appendChild(host);
		// Fonts are next/font vars on <body>; wait for the files BEFORE the
		// content mounts, so its entrance animations play in the real faces.
		// The intro's cover (SSR-injected CSS showing the logo) stays up
		// underneath the still-transparent host during this wait.
		await document.fonts.ready;
		await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
		content.innerHTML = html;
		host.appendChild(content);
		if (instant) {
			// The intro appears at once — its logo is rendered statically at the
			// same position the cover painted it, so the handoff is seamless.
			// Only then does the cover go; the transition is restored so the
			// fade-out at the end still plays.
			host.style.transition = "none";
			host.style.opacity = "1";
			await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
			document.getElementById("__demo_cover")?.remove();
			host.style.transition = "opacity 260ms ease";
		} else {
			document.getElementById("__demo_cover")?.remove();
			host.style.opacity = "1";
		}
		await sleep(300);
		await sleep(holdMs);
		if (!leaveUp) {
			host.style.opacity = "0";
			await sleep(320);
			host.remove();
		}
	}, inner);
}

const pad2 = (n: number) => String(n).padStart(2, "0");

export type TitleCardOpts = {
	index: number;
	total: number;
	eyebrow: string;
	title: string;
	sub: string;
};

/** Chapter card: `// EYEBROW  01 / 03`, staggered title, petrol bar, sub. */
export async function titleCard(page: Page, opts: TitleCardOpts): Promise<void> {
	const words = opts.title
		.split(" ")
		.map(
			(w, i) =>
				`<span class="dc-word" style="animation-delay:${140 + i * 90}ms">${w}</span>`,
		)
		.join(" ");
	const html = `
		<div class="dc-fade" style="animation-delay:80ms;display:flex;align-items:baseline;gap:16px;margin-bottom:28px;font-family:var(--font-ibm-plex-mono),ui-monospace,monospace;font-size:13px;font-weight:600;letter-spacing:0.16em;">
			<span style="color:#16606e;">${opts.eyebrow}</span>
			<span style="color:#8a9aa0;font-weight:500;">${pad2(opts.index)} / ${pad2(opts.total)}</span>
		</div>
		<h1 style="margin:0;font-family:var(--font-space-grotesk),sans-serif;font-weight:700;font-size:64px;line-height:1.06;letter-spacing:-0.03em;color:#101820;">${words}</h1>
		<div class="dc-bar" style="height:3px;background:#16606e;border-radius:2px;margin-top:28px;"></div>
		<p class="dc-fade" style="margin:26px 0 0;font-family:var(--font-hanken-grotesk),sans-serif;font-size:20px;line-height:1.5;color:#56646a;">${opts.sub}</p>
	`;
	await playCard(page, { css: CARD_CSS, html, holdMs: 2600, leaveUp: false });
}

export type BrandCardOpts = {
	tagline: string;
	/** Extra mono line under the tagline (e.g. the repo URL on the close card). */
	footer?: string;
	holdMs?: number;
	/** Keep the card on screen (close card — the recording ends on it). */
	leaveUp?: boolean;
	/** Mount fully opaque at once (intro card, so the page never blinks). */
	instant?: boolean;
};

/** Intro / close card: logo + wordmark + petrol bar + tagline. */
export async function brandCard(page: Page, opts: BrandCardOpts): Promise<void> {
	const footer = opts.footer
		? `<div class="dc-fade" style="animation-delay:760ms;margin-top:30px;font-family:var(--font-ibm-plex-mono),ui-monospace,monospace;font-size:14px;font-weight:500;letter-spacing:0.04em;color:#16606e;">${opts.footer}</div>`
		: "";
	const html = `
		<div style="display:flex;align-items:baseline;gap:18px;">
			<!-- The logo's ink fills only ~69% of its viewBox (15% padding below),
			     so at 72px the visible mark is ~50px (the wordmark's ascender
			     height) and needs an 11px drop to sit its ink on the baseline.
			     On the instant intro it renders statically — the pre-card cover
			     already shows it at this exact spot (video poster frame). -->
			<img src="/logo.svg" alt="" width="72" height="72" ${opts.instant ? "" : 'class="dc-word"'} style="animation-delay:80ms;position:relative;bottom:-11px;" />
			<span ${opts.instant ? "" : 'class="dc-word"'} style="animation-delay:160ms;font-family:var(--font-space-grotesk),sans-serif;font-weight:700;font-size:72px;line-height:1;letter-spacing:-0.03em;color:#101820;">auxilia</span>
		</div>
		<div class="dc-bar" style="--dc-bar-w:236px;height:3px;background:#16606e;border-radius:2px;margin-top:12px;"></div>
		<p class="dc-fade" style="margin:22px 0 0;font-family:var(--font-hanken-grotesk),sans-serif;font-size:20px;color:#56646a;">${opts.tagline}</p>
		${footer}
	`;
	await playCard(page, {
		css: CARD_CSS,
		html,
		holdMs: opts.holdMs ?? 2400,
		leaveUp: opts.leaveUp ?? false,
		instant: opts.instant ?? false,
	});
}

/* ------------------------------------------------------------------ */
/* Fake cursor — Playwright's real pointer is invisible in recordings,  */
/* so clicks are led by an injected cursor that glides to the target    */
/* and pulses a petrol ring on press (like the Remotion promo).         */
/* ------------------------------------------------------------------ */

const CURSOR_ID = "__demo_cursor";
// The SVG hotspot (arrow tip) sits ~4px right / 3px down of the element origin.
const CURSOR_HOTSPOT = { x: 4, y: 3 };
// Survives full-page navigations (the DOM node doesn't) — the cursor is
// re-injected at its last position instead of teleporting to the default.
let cursorPos = { x: 720, y: 780 };

async function ensureCursor(page: Page): Promise<void> {
	await page.evaluate(
		({ id, x, y }) => {
			if (document.getElementById(id)) return;
			const el = document.createElement("div");
			el.id = id;
			el.style.cssText =
				"position:fixed;left:0;top:0;z-index:2147483000;pointer-events:none;" +
				`transform:translate(${x}px,${y}px);will-change:transform;` +
				"filter:drop-shadow(0 2px 4px rgba(10,25,30,0.35));";
			el.innerHTML =
				'<div data-ring style="position:absolute;left:-6px;top:-6px;width:32px;height:32px;border-radius:50%;border:2px solid #16606E;opacity:0;"></div>' +
				'<svg data-arrow width="22" height="22" viewBox="0 0 24 24" style="position:relative;">' +
				'<path d="M5 3l15 7.5-6.2 1.8L11 19 5 3z" fill="#ffffff" stroke="#101820" stroke-width="1.5" stroke-linejoin="round"/></svg>';
			document.body.appendChild(el);
		},
		{ id: CURSOR_ID, x: cursorPos.x - CURSOR_HOTSPOT.x, y: cursorPos.y - CURSOR_HOTSPOT.y },
	);
}

/** Glide the cursor onto a target element (speed scales with distance). */
export async function cursorMoveTo(page: Page, target: Locator): Promise<void> {
	await target.scrollIntoViewIfNeeded();
	await ensureCursor(page);
	const box = await target.boundingBox();
	if (!box) return;
	const x = box.x + box.width / 2;
	const y = box.y + box.height / 2;
	const duration = Math.max(
		160,
		paced(Math.max(300, Math.min(850, Math.hypot(x - cursorPos.x, y - cursorPos.y) * 1.1))),
	);
	cursorPos = { x, y };
	await page.evaluate(
		({ id, x, y, duration }) => {
			const el = document.getElementById(id);
			if (!el) return;
			el.style.transition = `transform ${duration}ms cubic-bezier(0.22, 1, 0.36, 1)`;
			el.style.transform = `translate(${x}px, ${y}px)`;
		},
		{
			id: CURSOR_ID,
			x: x - CURSOR_HOTSPOT.x,
			y: y - CURSOR_HOTSPOT.y,
			duration,
		},
	);
	await page.waitForTimeout(duration + 60);
}

/** Glide to the element, pulse the press ring, then really click it. */
export async function cursorClick(
	page: Page,
	target: Locator,
	options?: Parameters<Locator["click"]>[0],
): Promise<void> {
	await cursorMoveTo(page, target);
	await page.evaluate((id) => {
		const el = document.getElementById(id);
		const arrow = el?.querySelector<SVGElement>("[data-arrow]");
		const ring = el?.querySelector<HTMLElement>("[data-ring]");
		if (arrow) {
			arrow.style.transition = "transform 120ms ease";
			arrow.style.transform = "scale(0.82)";
			setTimeout(() => {
				arrow.style.transform = "scale(1)";
			}, 150);
		}
		ring?.animate(
			[
				{ opacity: 0.9, transform: "scale(0.4)" },
				{ opacity: 0, transform: "scale(1.2)" },
			],
			{ duration: 420, easing: "ease-out" },
		);
	}, CURSOR_ID);
	await page.waitForTimeout(paced(140));
	await target.click(options);
}

/* ------------------------------------------------------------------ */
/* API scene — a Petrol Mono dark terminal that types the curl command  */
/* and prints the agent's REAL reply (the request runs concurrently).   */
/* ------------------------------------------------------------------ */

export type ApiSceneOpts = {
	/** Command lines to type (rendered after a `$ ` prompt). */
	command: string[];
	/** The real request; its resolved text is printed as the response body. */
	run: () => Promise<string>;
};

type TermSeg = { t: string; c: string };

/**
 * Colorize one command line with the login dark-panel palette
 * (design/README.md): teal command, green strings, peach env vars, grey body.
 */
function colorizeCommandLine(line: string): TermSeg[] {
	const segs: TermSeg[] = [];
	const re = /\$[A-Z_]+|"[^"]*"|\bcurl\b/g;
	let last = 0;
	for (const m of line.matchAll(re)) {
		if (m.index > last) segs.push({ t: line.slice(last, m.index), c: "#c9d4d6" });
		const t = m[0];
		const c = t.startsWith("$") ? "#e8a085" : t.startsWith('"') ? "#7bc7a9" : "#9fd6cb";
		segs.push({ t, c });
		last = m.index + t.length;
	}
	if (last < line.length) segs.push({ t: line.slice(last), c: "#c9d4d6" });
	return segs;
}

export async function apiScene(page: Page, opts: ApiSceneOpts): Promise<void> {
	const resultPromise = opts.run();
	// The run races the typing animation below — mark rejections as handled
	// so a failure mid-animation can't crash the process as an unhandled
	// rejection; the `await resultPromise` further down still throws.
	resultPromise.catch(() => {});
	const segLines = opts.command.map(colorizeCommandLine);

	// Mount the terminal and type the command while the run is in flight.
	// The scene follows the walkthrough pacing (DEMO_SPEED) like everything else.
	const delays = {
		settle: paced(500),
		char: Math.max(5, paced(14)),
		newline: paced(120),
		hold: paced(6000),
	};
	await page.evaluate(
		async ({ segLines, delays }) => {
			const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
			const host = document.createElement("div");
			host.id = "__demo_api_scene";
			host.style.cssText =
				"position:fixed;inset:0;z-index:2147483200;background:#f6f8f8;" +
				"display:flex;align-items:center;justify-content:center;" +
				"opacity:0;transition:opacity 280ms ease;";
			// The terminal mirrors the login page's dark panel: #101820, a 40px
			// teal grid overlay, and the same text palette.
			const grid =
				"background-image:linear-gradient(rgba(159,214,203,0.05) 1px,transparent 1px)," +
				"linear-gradient(90deg,rgba(159,214,203,0.05) 1px,transparent 1px);" +
				"background-size:40px 40px;";
			host.innerHTML = `
				<div style="width:960px;border-radius:14px;background:#101820;border:1px solid rgba(255,255,255,0.08);box-shadow:0 40px 90px -30px rgba(10,25,30,0.5);overflow:hidden;${grid}">
					<div style="height:42px;display:flex;align-items:center;gap:8px;padding:0 16px;border-bottom:1px solid rgba(255,255,255,0.08);">
						<span style="width:11px;height:11px;border-radius:50%;background:#FF5F57;"></span>
						<span style="width:11px;height:11px;border-radius:50%;background:#FEBC2E;"></span>
						<span style="width:11px;height:11px;border-radius:50%;background:#28C840;"></span>
						<span style="margin-left:10px;font-family:var(--font-ibm-plex-mono),ui-monospace,monospace;font-size:12px;letter-spacing:0.08em;color:#5a6e74;">// CALL YOUR AGENT OVER HTTP</span>
					</div>
					<pre data-term style="margin:0;padding:22px 24px 26px;min-height:340px;font-family:var(--font-ibm-plex-mono),ui-monospace,monospace;font-size:13.5px;line-height:23px;color:#c9d4d6;white-space:pre-wrap;word-break:break-all;"></pre>
				</div>`;
			document.body.appendChild(host);
			await document.fonts.ready;
			await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
			host.style.opacity = "1";
			await sleep(delays.settle);

			const term = host.querySelector("[data-term]") as HTMLElement;
			const prompt = document.createElement("span");
			prompt.style.color = "#9fd6cb";
			prompt.textContent = "$ ";
			term.appendChild(prompt);
			const cmd = document.createElement("span");
			term.appendChild(cmd);
			const caret = document.createElement("span");
			caret.style.color = "#9fd6cb";
			caret.textContent = "▋";
			let caretOn = true;
			const blink = setInterval(() => {
				caretOn = !caretOn;
				caret.style.opacity = caretOn ? "1" : "0.15";
			}, 350);
			term.appendChild(caret);

			// Type segment by segment so the colors appear as the text does.
			for (let i = 0; i < segLines.length; i++) {
				if (i > 0) {
					cmd.appendChild(document.createTextNode("\n"));
					await sleep(delays.newline);
				}
				for (const seg of segLines[i]) {
					const span = document.createElement("span");
					span.style.color = seg.c;
					cmd.appendChild(span);
					for (const ch of seg.t) {
						span.textContent += ch;
						await sleep(delays.char);
					}
				}
			}
			await sleep(delays.settle);
			clearInterval(blink);
			caret.remove();

			const running = document.createElement("div");
			running.setAttribute("data-running", "");
			running.style.cssText = "margin-top:14px;color:#5a6e74;";
			running.textContent = "→ run accepted — the agent is calling its MCP tools…";
			term.appendChild(running);
		},
		{ segLines, delays },
	);

	// Wait for the real reply, then print it and let it breathe.
	const content = await resultPromise;
	await page.evaluate(
		async ({ text, holdMs }) => {
			const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
			const host = document.getElementById("__demo_api_scene");
			const term = host?.querySelector("[data-term]");
			if (!host || !term) return;
			term.querySelector("[data-running]")?.remove();
			const block = document.createElement("div");
			block.style.cssText = "margin-top:14px;opacity:0;transition:opacity 400ms ease;";
			// Built with textContent (never markup) — the reply is model output.
			// JSON.stringify renders it exactly as a real curl body would:
			// quoted, with newlines and quotes escaped.
			const span = (color: string, value: string, bold = false) => {
				const el = document.createElement("span");
				el.style.color = color;
				if (bold) el.style.fontWeight = "600";
				el.textContent = value;
				return el;
			};
			block.append(
				span("#7bc7a9", "HTTP/2 200 OK\n"),
				span("#c9d4d6", "{\n"),
				span("#9fd6cb", '  "content"'),
				span("#c9d4d6", ": "),
				span("#ffffff", JSON.stringify(text), true),
				span("#c9d4d6", "\n}"),
			);
			term.appendChild(block);
			await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
			block.style.opacity = "1";
			await sleep(holdMs);
			host.style.opacity = "0";
			await sleep(320);
			host.remove();
		},
		{ text: content, holdMs: delays.hold },
	);
}

/** Type into a locator with a human-looking cadence, cursor-led. */
export async function humanType(page: Page, selector: string, text: string): Promise<void> {
	const locator = page.locator(selector);
	await cursorClick(page, locator);
	await locator.pressSequentially(text, { delay: paced(22) });
}

/** A beat between demo actions so the video is watchable (DEMO_SPEED-scaled). */
export async function beat(page: Page, ms = 900): Promise<void> {
	await page.waitForTimeout(paced(ms));
}
