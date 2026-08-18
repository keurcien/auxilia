"use client";

import { useEffect, useMemo, useState } from "react";

const DEFAULT_ICON =
	"https://pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev/assets/icons/mcp.png";

const BADGES = {
	oauth2: { label: "OAUTH 2.0", className: "pm-badge-oauth" },
	api_key: { label: "API KEY", className: "pm-badge-neutral" },
	none: { label: "OPEN", className: "pm-badge-neutral" },
};

function AuthBadge({ authType }) {
	const badge = BADGES[authType] ?? BADGES.none;
	return (
		<span className={`pm-catalog-badge ${badge.className}`}>{badge.label}</span>
	);
}

function CatalogCard({ server }) {
	return (
		<div className="pm-catalog-card">
			<div className="pm-catalog-card-head">
				<span className="pm-catalog-icon">
					<img src={server.iconUrl ?? DEFAULT_ICON} alt="" loading="lazy" />
				</span>
				<div className="pm-catalog-id">
					<div className="pm-catalog-name-row">
						<span className="pm-catalog-name">{server.name}</span>
						<AuthBadge authType={server.authType} />
					</div>
					<div className="pm-catalog-url">{server.url}</div>
				</div>
			</div>
			<p className="pm-catalog-desc">
				{server.description || "No description provided."}
			</p>
		</div>
	);
}

export function MCPCatalog() {
	const [servers, setServers] = useState(null); // null = loading
	const [failed, setFailed] = useState(false);
	const [query, setQuery] = useState("");

	useEffect(() => {
		const controller = new AbortController();
		void (async () => {
			try {
				const res = await fetch("/api/mcp-catalog", {
					signal: controller.signal,
				});
				if (!res.ok) throw new Error("unavailable");
				const data = await res.json();
				setServers(data.servers ?? []);
			} catch {
				if (!controller.signal.aborted) setFailed(true);
			}
		})();
		return () => {
			controller.abort();
		};
	}, []);

	const filtered = useMemo(() => {
		if (!servers) return [];
		const q = query.trim().toLowerCase();
		if (!q) return servers;
		return servers.filter(
			(server) =>
				server.name.toLowerCase().includes(q) ||
				(server.description ?? "").toLowerCase().includes(q),
		);
	}, [servers, query]);

	if (failed) {
		return (
			<div className="pm-catalog-empty">
				The official catalog is unavailable right now — see the{" "}
				<a
					href="https://github.com/keurcien/auxilia/blob/main/backend/app/mcp/servers/catalog.yaml"
					target="_blank"
					rel="noreferrer"
				>
					bundled snapshot
				</a>{" "}
				for the list it falls back to.
			</div>
		);
	}

	return (
		<div className="pm-catalog">
			<div className="pm-catalog-toolbar">
				<input
					type="search"
					className="pm-catalog-search"
					placeholder="Search the catalog…"
					value={query}
					onChange={(event) => {
						setQuery(event.target.value);
					}}
				/>
				{servers && (
					<span className="pm-catalog-count">
						{servers.length} server{servers.length === 1 ? "" : "s"}
					</span>
				)}
			</div>
			{servers === null ? (
				<div className="pm-catalog-grid">
					{Array.from({ length: 6 }, (_, i) => (
						<div key={i} className="pm-catalog-skeleton" />
					))}
				</div>
			) : filtered.length > 0 ? (
				<div className="pm-catalog-grid">
					{filtered.map((server) => (
						<CatalogCard key={server.url} server={server} />
					))}
				</div>
			) : (
				<div className="pm-catalog-empty">
					No catalog servers match your search.
				</div>
			)}
		</div>
	);
}
