const PUBLIC_PATHS = ["/auth", "/setup", "/invite"];

/**
 * Called on any 401 and when the tab regains focus: if the session is really
 * gone, reload so `proxy.ts` clears the cookie and sends the user to
 * `/auth?next=<this page>`. Checking `/auth/me` (not the 401 itself) keeps the
 * MCP `oauth_required` 401 and bad-password 401s from logging anyone out.
 */
export function ensureSignedIn(): Promise<void> {
	const { pathname } = window.location;
	if (PUBLIC_PATHS.some((path) => pathname.startsWith(path))) {
		return Promise.resolve();
	}
	// A burst of 401s (one expiry, many requests) shares one check.
	inFlight ??= checkSession().finally(() => {
		inFlight = null;
	});
	return inFlight;
}

let inFlight: Promise<void> | null = null;

async function checkSession(): Promise<void> {
	try {
		// Time-boxed: a hung probe would otherwise hold `inFlight` forever.
		const res = await fetch("/api/backend/auth/me", {
			credentials: "include",
			signal: AbortSignal.timeout(10_000),
		});
		if (res.status === 401) window.location.reload();
	} catch {
		// Offline / backend down — not a sign-out; the next check retries.
	}
}
