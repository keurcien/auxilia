export const DEFAULT_ICON =
	"https://pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev/assets/icons/mcp.png";

const CDN_HOST = "pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev";

/** Servers whose icon is hosted on our CDN come from the official catalog. */
export function isOfficialIcon(url?: string | null): boolean {
	return url ? url.includes(CDN_HOST) : false;
}

export const slugify = (name: string) =>
	name.trim().toLowerCase().replace(/\s+/g, "-") || "…";
