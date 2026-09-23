#!/usr/bin/env node
/**
 * Seed demo data into a running auxilia backend.
 *
 * Reconciles (delete-and-recreate for its own named resources, so spec
 * changes always converge):
 *   - the first admin user (via /auth/setup) or signs in if setup is done
 *   - seven workspace MCP servers: two public no-auth ones the demo chats
 *     against (Hugging Face, Context7) and five installed from the official
 *     catalog exactly as the one-click "Add" does (Notion, Slack, HubSpot,
 *     BigQuery, GitHub) — OAuth servers, connected per user later
 *   - six agents with real instructions, bound to those servers (tool maps
 *     synced where the server answers without credentials); the "Python
 *     Developer" is bound to a workspace sandbox (skipped with a warning when
 *     none is configured)
 *   - teams + display-only teammates for the sharing chapter
 *   - enables a model and sets a workspace default if none is set
 *
 * It deliberately does NOT create the DeepWiki or "Cloudflare Docs" servers
 * or the "Research Assistant" agent — those are created live on camera by
 * the demo walkthrough (DeepWiki via the official catalog's one-click Add).
 *
 * Usage:
 *   npm run demo:seed              reconcile the seed on top of what exists
 *   npm run demo:reset             WIPE every agent (and its threads), trigger
 *                                  and MCP server of the workspace, then seed —
 *                                  a clean slate for a recording. Refuses to
 *                                  run against a non-local backend unless
 *                                  DEMO_RESET_REMOTE=1. Skills, sandboxes,
 *                                  users, teams and models are kept.
 *
 * Env:
 *   BACKEND_URL        backend base URL       (default http://localhost:8000)
 *   DEMO_EMAIL         demo admin email       (default demo@auxilia.dev)
 *   DEMO_PASSWORD      demo admin password    (default auxilia-demo-123)
 *   DEMO_SANDBOX_NAME  sandbox to bind the Python Developer to (default: first)
 */

const BACKEND = (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/$/, "");
const ADMIN = {
	email: process.env.DEMO_EMAIL ?? "demo@auxilia.dev",
	password: process.env.DEMO_PASSWORD ?? "auxilia-demo-123",
	name: "Demo Admin",
};

// Official logos served from the workspace asset CDN.
const ICON_CDN = "https://pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev/assets/icons";

// Public, no-auth remote MCP servers that work out of the box — the agents
// bound to them chat for real on camera.
const MCP_SERVERS = [
	{
		name: "Hugging Face",
		url: "https://huggingface.co/mcp",
		auth_type: "none",
		description: "Search models, datasets and spaces on the Hugging Face Hub.",
		icon_url: `${ICON_CDN}/huggingface.png`,
	},
	{
		name: "Context7",
		url: "https://mcp.context7.com/mcp",
		auth_type: "none",
		description: "Up-to-date documentation for any library or framework.",
		icon_url: `${ICON_CDN}/context7.png`,
	},
];

// Official-catalog servers installed the way the "Add" button does it: the
// entry (URL, auth type, icon, description) is copied from the live catalog
// the backend serves. They are OAuth servers — each user connects their own
// account from the server card, so the seed never needs credentials. Static
// OAuth clients (HubSpot, BigQuery, GitHub, Slack) can be given later from the
// server's edit form.
const CATALOG_SERVERS = ["Notion", "Slack", "HubSpot", "BigQuery", "GitHub"];

// Six agents modelled on what real workspaces run (a docs researcher, an
// ML librarian, a Python developer, a data analyst, an HR assistant, a CRM
// copilot). `serverNames` are bound in that order; tool maps default to
// everything allowed, with `approval` naming the tools that pause for a human.
const AGENTS = [
	{
		name: "Docs Researcher",
		emoji: "📚",
		color: "#0984E3",
		description: "Answers questions from up-to-date library docs.",
		instructions: [
			"You are a documentation researcher for the engineering team.",
			"",
			"When asked about a library or framework, resolve it with your documentation tools first, then query the docs for the exact question — never answer from memory when a lookup is possible.",
			"",
			"Answer in a few sentences, with a short code example when it helps. Name the library version you consulted and link the page you used. If the docs don't cover the question, say so plainly instead of guessing.",
		].join("\n"),
		serverNames: ["Context7"],
	},
	{
		name: "Model Scout",
		emoji: "🧭",
		color: "#6C5CE7",
		description: "Finds models and datasets on the Hugging Face Hub.",
		instructions: [
			"You are a machine-learning librarian.",
			"",
			"When asked about models or datasets, search the Hugging Face Hub with your tools and recommend the best matches: name, task, license, size and a one-line rationale for each. Prefer actively maintained repositories with a model card.",
			"",
			"For a digest or a trend question, group results by task and keep it under ten lines. Always link the Hub page.",
		].join("\n"),
		serverNames: ["Hugging Face"],
	},
	{
		name: "Python Developer",
		emoji: "🐍",
		color: "#E17055",
		description: "Writes and runs Python in a sandbox.",
		instructions: [
			"You are a Python developer with a sandbox.",
			"",
			"When a question can be answered by code — dates, arithmetic, parsing, data wrangling, quick simulations — write a small script, run it, and report the executed result rather than computing in your head.",
			"",
			"Keep scripts self-contained and under /tmp. Install a missing package with pip before importing it. When a run fails, read the traceback, fix the script and run it again; show the final code only when the user asks for it.",
		].join("\n"),
		useSandbox: true,
	},
	{
		name: "Data Analyst",
		emoji: "📊",
		color: "#00B894",
		description: "Answers business questions from the warehouse and posts results to Slack.",
		instructions: [
			"You are the team's data analyst, working on the BigQuery warehouse.",
			"",
			"Before writing SQL, look up the dataset and table schemas with your tools — never guess column names. Prefer read-only queries; when a question needs more than one, run them one at a time and explain what each one measures.",
			"",
			"Report numbers with their period and unit, and state the query you ran so it can be checked. Round sensibly. If a metric is ambiguous (revenue vs. GMV, orders vs. items), ask before querying.",
			"",
			"Only post to Slack when the user asks you to. Posts are short: one headline number, two or three supporting lines, and a link back to this thread.",
		].join("\n"),
		serverNames: ["BigQuery", "Slack"],
	},
	{
		name: "HR Assistant",
		emoji: "🧑‍💼",
		color: "#FDCB6E",
		description: "Answers employee questions from the HR handbook in Notion.",
		instructions: [
			"You are the HR assistant. You answer employees' questions about leave, benefits, expenses, onboarding and internal policies using the HR handbook in Notion.",
			"",
			"Start by searching the HR space for the topic, then read the page(s) that match before answering. Quote the policy in the employee's words, link the page you used, and mention the date of the last update when the page shows one.",
			"",
			"Never invent a policy. If nothing in Notion covers the question, say so and point the employee to the HR team. Do not give legal or medical advice; for individual situations (salary, disputes, health), suggest a conversation with HR instead of an answer.",
		].join("\n"),
		serverNames: ["Notion"],
	},
	{
		name: "Sales Assistant",
		emoji: "💼",
		color: "#E84393",
		description: "Researches prospects in HubSpot and drafts outreach for a human to send.",
		instructions: [
			"You are a sales research assistant for the revenue team. You research prospects and draft outreach — you never send anything yourself.",
			"",
			"Start from HubSpot: look up the contact, company and open deals before anything else, and always cite the HubSpot record you used. Gather the contact's role, the company's industry and size, and the current deal stage.",
			"",
			"When drafting outreach, keep it under 120 words, friendly and specific. Never invent facts; leave out what you cannot verify. Present the draft for review.",
			"",
			"Writes to HubSpot (notes, tasks, property updates) and Slack messages need a human's approval — propose them, don't assume.",
		].join("\n"),
		serverNames: ["HubSpot", "Slack"],
	},
];

// Installed on camera by the walkthrough — the seed must make sure it is NOT
// already installed, or the catalog card shows "Added" instead of "Add".
const WALKTHROUGH_CATALOG_URL = "https://mcp.deepwiki.com/mcp";

// Teams + teammates for the "Share your agents" chapter (and a lively Users
// page). Colors come from the backend's ALLOWED_COLORS palette. Teammates
// are display-only members — no password, they never sign in.
const TEAMS = [
	{ name: "Data", color: "#0984E3" },
	{ name: "Engineering", color: "#6C5CE7" },
	{ name: "Marketing", color: "#E17055" },
	{ name: "Finance", color: "#00B894" },
];

const TEAMMATES = [
	{ name: "Alice", email: "alice@auxilia.dev", team: "Data" },
	{ name: "Bob", email: "bob@auxilia.dev", team: "Engineering" },
	{ name: "John Doe", email: "john.doe@auxilia.dev", team: "Marketing" },
];

let token = null;

async function api(method, path, body, { expect = [200, 201, 204], optional = false } = {}) {
	const res = await fetch(`${BACKEND}${path}`, {
		method,
		headers: {
			"content-type": "application/json",
			...(token ? { authorization: `Bearer ${token}` } : {}),
		},
		body: body === undefined ? undefined : JSON.stringify(body),
	});
	if (!expect.includes(res.status)) {
		const text = await res.text();
		if (optional) {
			console.warn(`  ⚠ ${method} ${path} → ${res.status} ${text.slice(0, 200)}`);
			return null;
		}
		throw new Error(`${method} ${path} → ${res.status} ${text.slice(0, 500)}`);
	}
	const setCookie = res.headers.getSetCookie?.() ?? [];
	const auth = setCookie.find((c) => c.startsWith("access_token="));
	if (auth) token = auth.split(";")[0].split("=").slice(1).join("=");
	if (res.status === 204) return null;
	return res.json();
}

async function authenticate() {
	const status = await api("GET", "/auth/setup/status");
	if (status.setup_required) {
		await api("POST", "/auth/setup", ADMIN, { expect: [201] });
		console.log(`✔ created admin ${ADMIN.email}`);
		return;
	}
	// Setup is done — the demo admin can only be created on a fresh workspace,
	// so on an existing one we sign in with whatever credentials we were given.
	try {
		await api("POST", "/auth/signin", { email: ADMIN.email, password: ADMIN.password });
	} catch (err) {
		if (String(err?.message).includes("→ 401")) {
			console.error(
				`✗ Sign-in failed for ${ADMIN.email} — this workspace already has users,\n` +
					`  so the demo admin cannot be created via /auth/setup.\n\n` +
					`  Either seed with an existing ADMIN account:\n` +
					`    DEMO_EMAIL=you@example.com DEMO_PASSWORD=... npm run demo:seed\n\n` +
					`  Or start from a fresh database (creates ${ADMIN.email}):\n` +
					`    make reset && make dev`,
			);
			process.exit(1);
		}
		throw err;
	}
	console.log(`✔ signed in as ${ADMIN.email}`);
}

/** Delete seed-owned agents and servers so re-seeding always converges. */
/** Remove this seed's own resources so the run converges. */
async function removeStaleResources(catalog) {
	const agents = await api("GET", "/agents/");
	const seedAgentNames = new Set(AGENTS.map((a) => a.name));
	for (const agent of agents) {
		if (seedAgentNames.has(agent.name)) {
			await api("DELETE", `/agents/${agent.id}/permanent`);
		}
	}
	const servers = await api("GET", "/mcp-servers/");
	const seedUrls = new Set([
		...MCP_SERVERS.map((s) => s.url),
		...catalog.map((s) => s.url),
		WALKTHROUGH_CATALOG_URL,
	]);
	for (const server of servers) {
		if (seedUrls.has(server.url)) {
			await api("DELETE", `/mcp-servers/${server.id}?detach_agents=true`);
		}
	}
}

/**
 * `--clean`: wipe every trigger, agent (with its threads and checkpoints —
 * the permanent delete purges them) and MCP server in the workspace, so a
 * recording starts from exactly the seed. Skills, sandboxes, users, teams and
 * models are kept. Archived agents go too.
 */
async function wipeWorkspace() {
	const local = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(BACKEND);
	if (!local && process.env.DEMO_RESET_REMOTE !== "1") {
		console.error(
			`✗ --clean refuses to wipe a non-local backend (${BACKEND}). Set DEMO_RESET_REMOTE=1 if you really mean it.`,
		);
		process.exit(1);
	}
	const triggers = await api("GET", "/triggers/");
	for (const trigger of triggers) await api("DELETE", `/triggers/${trigger.id}`);
	const agents = [
		...(await api("GET", "/agents/")),
		...(await api("GET", "/agents/?archived=true")),
	];
	const seen = new Set();
	let threads = 0;
	for (const agent of agents) {
		if (seen.has(agent.id)) continue;
		seen.add(agent.id);
		const page = await api("GET", `/agents/${agent.id}/threads?limit=1`, undefined, {
			optional: true,
		});
		threads += page?.total ?? 0;
		await api("DELETE", `/agents/${agent.id}/permanent`);
	}
	const servers = await api("GET", "/mcp-servers/");
	for (const server of servers) {
		await api("DELETE", `/mcp-servers/${server.id}?detach_agents=true`);
	}
	console.log(
		`✔ wiped ${triggers.length} triggers, ${seen.size} agents (${threads} threads), ${servers.length} MCP servers\n`,
	);
}

/** The official catalog as the backend serves it — the source of one-click installs. */
async function loadCatalog() {
	// Not optional: the agents below bind these servers, and an agent seeded
	// without its servers has no tools — the on-camera chats would refuse to
	// start. Better to stop here with the real cause.
	const entries = await api("GET", "/mcp-servers/official");
	const byName = new Map(entries.map((e) => [e.name, e]));
	const missing = CATALOG_SERVERS.filter((name) => !byName.has(name));
	if (missing.length > 0) {
		throw new Error(
			`catalog entries not found: ${missing.join(", ")} — the official catalog changed; update CATALOG_SERVERS`,
		);
	}
	return CATALOG_SERVERS.map((name) => byName.get(name));
}

async function seedMcpServers(catalog) {
	const servers = {};
	for (const spec of MCP_SERVERS) {
		servers[spec.name] = await api("POST", "/mcp-servers/", spec, { expect: [201] });
		console.log(`✔ created MCP server "${spec.name}"`);
	}
	for (const entry of catalog) {
		// Same payload as the catalog card's Add button: the entry, verbatim.
		servers[entry.name] = await api(
			"POST",
			"/mcp-servers/",
			{
				name: entry.name,
				url: entry.url,
				auth_type: entry.auth_type,
				icon_url: entry.icon_url,
				description: entry.description,
			},
			{ expect: [201] },
		);
		console.log(`✔ installed "${entry.name}" from the catalog (${entry.auth_type})`);
	}
	return servers;
}

async function seedAgents(servers, sandbox) {
	for (const spec of AGENTS) {
		if (spec.useSandbox && !sandbox) {
			console.warn(`  ⚠ skipping agent "${spec.name}" — no sandbox configured in this workspace`);
			continue;
		}
		const bound = (spec.serverNames ?? []).map((name) => {
			const server = servers[name];
			if (!server) {
				throw new Error(`agent "${spec.name}" binds "${name}", which was not seeded`);
			}
			return server;
		});
		const agent = await api(
			"POST",
			"/agents/",
			{
				name: spec.name,
				emoji: spec.emoji,
				color: spec.color,
				description: spec.description,
				instructions: spec.instructions,
				mcp_servers: bound.map((server) => ({ mcp_server_id: server.id, tools: null })),
				sandboxes: spec.useSandbox ? [{ sandbox_id: sandbox.id, tools: null }] : [],
			},
			{ expect: [201] },
		);
		console.log(
			`✔ created agent "${spec.name}"${spec.useSandbox ? ` (sandbox: ${sandbox.name})` : ""}`,
		);
		for (const server of bound) {
			// OAuth servers answer tools/list only for a connected user — their
			// map is synced when someone connects. No-auth servers sync now.
			if (server.auth_type !== "none") continue;
			const synced = await api(
				"POST",
				`/agents/${agent.id}/mcp-servers/${server.id}/sync-tools`,
				undefined,
				{ optional: true },
			);
			// sync-tools returns tools=null when the remote server is
			// unreachable — the agent would then refuse to chat.
			if (synced?.tools && Object.keys(synced.tools).length > 0) {
				console.log(`  ✔ synced ${Object.keys(synced.tools).length} tools from "${server.name}"`);
			} else {
				console.warn(`  ⚠ "${server.name}" returned no tools — is ${server.url} reachable?`);
			}
		}
	}
}

/** Teams and display-only teammates for the sharing chapter (idempotent). */
async function seedTeamsAndUsers() {
	const existingTeams = await api("GET", "/teams/");
	const teamsByName = new Map(existingTeams.map((t) => [t.name, t]));
	for (const spec of TEAMS) {
		if (teamsByName.has(spec.name)) continue;
		const team = await api("POST", "/teams/", spec, { expect: [201] });
		teamsByName.set(team.name, team);
		console.log(`✔ created team "${spec.name}"`);
	}

	const users = await api("GET", "/users/?limit=200");
	const usersByEmail = new Map(users.items.map((u) => [u.email, u]));
	for (const spec of TEAMMATES) {
		let user = usersByEmail.get(spec.email);
		if (!user) {
			user = await api(
				"POST",
				"/users/",
				{ name: spec.name, email: spec.email, role: "member" },
				{ expect: [200, 201] },
			);
			console.log(`✔ created user "${spec.name}"`);
		}
		const team = teamsByName.get(spec.team);
		if (team && user.team_id !== team.id) {
			await api("PATCH", `/users/${user.id}/team`, { team_id: team.id });
			console.log(`  ✔ assigned "${spec.name}" to ${spec.team}`);
		}
	}
}

async function seedDefaultModel() {
	const models = await api("GET", "/model-providers/models/manage", undefined, { optional: true });
	if (!models) {
		console.warn("  ⚠ could not list models — is an LLM provider API key set in .env?");
		return;
	}
	const usable = models.filter((m) => !m.deprecated);
	if (usable.length === 0) {
		console.warn("  ⚠ no usable models — set an LLM provider API key in .env and restart the backend");
		return;
	}
	if (usable.some((m) => m.is_default)) {
		console.log("• workspace default model already set");
		return;
	}
	const preferred =
		usable.find((m) => m.is_enabled) ??
		usable.find((m) => /haiku|mini|flash/i.test(m.model_id)) ??
		usable[0];
	if (!preferred.is_enabled) {
		await api(
			"PUT",
			`/model-providers/models/${preferred.provider}/${encodeURIComponent(preferred.model_id)}`,
			{ is_enabled: true },
		);
		console.log(`✔ enabled model ${preferred.provider}/${preferred.model_id}`);
	}
	await api("PUT", "/model-providers/models/default", {
		provider: preferred.provider,
		model_id: preferred.model_id,
	});
	console.log(`✔ set default model ${preferred.provider}/${preferred.model_id}`);
}

const clean = process.argv.includes("--clean");
console.log(`${clean ? "Resetting and seeding" : "Seeding"} demo data into ${BACKEND}\n`);
await authenticate();
const catalog = await loadCatalog();
if (clean) await wipeWorkspace();
else await removeStaleResources(catalog);
const sandboxes = await api("GET", "/sandboxes/", undefined, { optional: true });
const sandbox =
	sandboxes?.find((s) => s.name === process.env.DEMO_SANDBOX_NAME) ?? sandboxes?.[0] ?? null;
const servers = await seedMcpServers(catalog);
await seedAgents(servers, sandbox);
await seedTeamsAndUsers();
await seedDefaultModel();
console.log("\nDone. Demo credentials:");
console.log(`  email:    ${ADMIN.email}`);
console.log(`  password: ${ADMIN.password}`);
