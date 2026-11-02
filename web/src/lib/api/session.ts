const PUBLIC_PATHS = [
	"/auth",
	"/setup",
	"/invite",
	"/share",
	"/two-factor",
	"/forgot-password",
	"/reset-password",
];

let inFlight: Promise<void> | null = null;

function isPathWithin(pathname: string, root: string): boolean {
	return pathname === root || pathname.startsWith(`${root}/`);
}

/**
 * Confirm an apparent 401 is an expired session before reloading. This keeps
 * MCP authorization-required responses and bad sign-in attempts from logging
 * out an otherwise authenticated user.
 */
export function ensureSignedIn(): Promise<void> {
	const { pathname } = window.location;
	if (PUBLIC_PATHS.some((path) => isPathWithin(pathname, path))) {
		return Promise.resolve();
	}
	inFlight ??= checkSession().finally(() => {
		inFlight = null;
	});
	return inFlight;
}

async function checkSession(): Promise<void> {
	try {
		const response = await fetch("/api/backend/auth/me", {
			credentials: "include",
			signal: AbortSignal.timeout(10_000),
		});
		if (response.status === 401) window.location.reload();
	} catch {
		// Offline and backend failures are not proof that the session ended.
	}
}
