const UUID_SEGMENT =
	"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";

const DETAIL_ROUTES: Array<{ pattern: RegExp; listing: string }> = [
	{ pattern: new RegExp(`^/agents/${UUID_SEGMENT}(?:/|$)`, "i"), listing: "/agents" },
	{
		pattern: new RegExp(`^/mcp-servers/${UUID_SEGMENT}(?:/|$)`, "i"),
		listing: "/mcp-servers",
	},
	{ pattern: new RegExp(`^/skills/${UUID_SEGMENT}(?:/|$)`, "i"), listing: "/skills" },
	{
		pattern: new RegExp(`^/triggers/${UUID_SEGMENT}(?:/|$)`, "i"),
		listing: "/triggers",
	},
];

export function workspaceSwitchDestination(
	pathname: string,
	search = "",
	hash = "",
): string {
	const detail = DETAIL_ROUTES.find(({ pattern }) => pattern.test(pathname));
	return detail?.listing ?? `${pathname}${search}${hash}`;
}

export function currentWorkspaceSwitchDestination(): string {
	return workspaceSwitchDestination(
		window.location.pathname,
		window.location.search,
		window.location.hash,
	);
}
