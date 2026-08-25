#!/usr/bin/env node
/**
 * Seed demo data into a running auxilia backend.
 *
 * Reconciles (delete-and-recreate for its own named resources, so spec
 * changes always converge):
 *   - the first admin user (via /auth/setup) or signs in if setup is done
 *   - two public no-auth MCP servers (Hugging Face, Context7)
 *   - agents bound to them, with tool maps synced
 *   - a "Python Developer" agent bound to the workspace's first sandbox (skipped
 *     with a warning when no sandbox is configured)
 *   - enables a model and sets a workspace default if none is set
 *
 * It deliberately does NOT create the DeepWiki or "Microsoft Learn" servers
 * or the "Research Assistant" agent — those are created live on camera by
 * the demo walkthrough (DeepWiki via the official catalog's one-click Add).
 *
 * Usage:
 *   npm run demo:seed        (or: node tests/demo/seed-demo.mjs)
 *
 * Env:
 *   BACKEND_URL    backend base URL       (default http://localhost:8000)
 *   DEMO_EMAIL     demo admin email       (default demo@auxilia.dev)
 *   DEMO_PASSWORD  demo admin password    (default auxilia-demo-123)
 */

const BACKEND = (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/$/, "");
const ADMIN = {
	email: process.env.DEMO_EMAIL ?? "demo@auxilia.dev",
	password: process.env.DEMO_PASSWORD ?? "auxilia-demo-123",
	name: "Demo Admin",
};

// Official logos served from the workspace asset CDN.
const ICON_CDN = "https://pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev/assets/icons";

// Public, no-auth remote MCP servers that work out of the box.
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

const AGENTS = [
	{
		name: "Docs Researcher",
		emoji: "📚",
		color: "#0984E3",
		description: "Answers questions from up-to-date library docs.",
		instructions:
			"You are a documentation researcher. When asked about a library or framework, " +
			"look it up with your documentation tools and answer from what you find. " +
			"Keep answers short and name the library version you consulted.",
		serverName: "Context7",
	},
	{
		name: "Model Scout",
		emoji: "🧭",
		color: "#6C5CE7",
		description: "Finds models and datasets on the Hugging Face Hub.",
		instructions:
			"You are a machine-learning librarian. When asked about models or datasets, " +
			"search the Hugging Face Hub with your tools and recommend the best matches, " +
			"with a one-line rationale for each.",
		serverName: "Hugging Face",
	},
	{
		name: "Python Developer",
		emoji: "🐍",
		color: "#E17055",
		description: "Writes and runs Python in a sandbox.",
		instructions:
			"You are a Python developer. When asked a question that code can answer, " +
			"write and run Python in your sandbox instead of computing in your head, " +
			"then report the executed result.",
		useSandbox: true,
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
async function removeStaleResources() {
	const agents = await api("GET", "/agents/");
	const seedAgentNames = new Set(AGENTS.map((a) => a.name));
	for (const agent of agents) {
		if (seedAgentNames.has(agent.name)) {
			await api("DELETE", `/agents/${agent.id}/permanent`);
		}
	}
	const servers = await api("GET", "/mcp-servers/");
	const seedUrls = new Set(MCP_SERVERS.map((s) => s.url));
	for (const server of servers) {
		if (seedUrls.has(server.url) || server.url === WALKTHROUGH_CATALOG_URL) {
			await api("DELETE", `/mcp-servers/${server.id}?detach_agents=true`);
		}
	}
}

async function seedMcpServers() {
	const servers = {};
	for (const spec of MCP_SERVERS) {
		servers[spec.name] = await api("POST", "/mcp-servers/", spec, { expect: [201] });
		console.log(`✔ created MCP server "${spec.name}"`);
	}
	return servers;
}

async function seedAgents(servers, sandbox) {
	for (const spec of AGENTS) {
		if (spec.useSandbox && !sandbox) {
			console.warn(`  ⚠ skipping agent "${spec.name}" — no sandbox configured in this workspace`);
			continue;
		}
		const server = spec.serverName ? servers[spec.serverName] : null;
		const agent = await api(
			"POST",
			"/agents/",
			{
				name: spec.name,
				emoji: spec.emoji,
				color: spec.color,
				description: spec.description,
				instructions: spec.instructions,
				mcp_servers: server ? [{ mcp_server_id: server.id, tools: null }] : [],
				sandboxes: spec.useSandbox ? [{ sandbox_id: sandbox.id, tools: null }] : [],
			},
			{ expect: [201] },
		);
		console.log(`✔ created agent "${spec.name}"${spec.useSandbox ? ` (sandbox: ${sandbox.name})` : ""}`);
		if (server) {
			// Discover the server's tools and persist the tool map — without
			// this the runtime exposes no tools for the binding.
			const synced = await api(
				"POST",
				`/agents/${agent.id}/mcp-servers/${server.id}/sync-tools`,
				undefined,
				{ optional: true },
			);
			// sync-tools returns tools=null when the remote server is
			// unreachable — the agent would then refuse to chat.
			if (synced?.tools && Object.keys(synced.tools).length > 0) {
				console.log(`  ✔ synced ${Object.keys(synced.tools).length} tools from "${spec.serverName}"`);
			} else {
				console.warn(`  ⚠ "${spec.serverName}" returned no tools — is ${server.url} reachable?`);
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

console.log(`Seeding demo data into ${BACKEND}\n`);
await authenticate();
await removeStaleResources();
const sandboxes = await api("GET", "/sandboxes/", undefined, { optional: true });
const sandbox = sandboxes?.[0] ?? null;
const servers = await seedMcpServers();
await seedAgents(servers, sandbox);
await seedTeamsAndUsers();
await seedDefaultModel();
console.log("\nDone. Demo credentials:");
console.log(`  email:    ${ADMIN.email}`);
console.log(`  password: ${ADMIN.password}`);
