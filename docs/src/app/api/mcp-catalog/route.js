import { parse } from "yaml";

// The canonical catalog file — the same one every auxilia deployment reads
// (backend/app/mcp/servers/settings.py). Fetched server-side because the CDN
// bucket sends no CORS headers, and revalidated hourly.
const CATALOG_URL =
	"https://pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev/mcp/catalog.yaml";

export const revalidate = 3600;

export async function GET() {
	try {
		const res = await fetch(CATALOG_URL, { next: { revalidate: 3600 } });
		if (!res.ok) {
			throw new Error(`catalog fetch failed: ${res.status}`);
		}
		const doc = parse(await res.text());
		// Normalize every field to the type the component renders and filters
		// on — a hand-edited catalog entry must never crash the page.
		const servers = (Array.isArray(doc?.servers) ? doc.servers : [])
			.filter((s) => s && typeof s.name === "string" && typeof s.url === "string")
			.map((s) => ({
				name: s.name,
				url: s.url,
				authType: typeof s.auth_type === "string" ? s.auth_type : "none",
				iconUrl: typeof s.icon_url === "string" ? s.icon_url : null,
				description: typeof s.description === "string" ? s.description : null,
			}));
		if (servers.length === 0) {
			throw new Error("catalog is empty");
		}
		return Response.json({ servers });
	} catch {
		return Response.json({ servers: null }, { status: 502 });
	}
}
