const PUBLIC_PATHS = ["/auth", "/setup", "/invite"];

/**
 * Called on any 401 and when the tab regains focus: if the session is really
 * gone, reload so `proxy.ts` clears the cookie and sends the user to
 * `/auth?next=<this page>`. Checking `/auth/me` (not the 401 itself) keeps the
 * MCP `oauth_required` 401 and bad-password 401s from logging anyone out.
 */
export async function ensureSignedIn(): Promise<void> {
	const { pathname } = window.location;
	if (PUBLIC_PATHS.some((path) => pathname.startsWith(path))) return;
	try {
		const res = await fetch("/api/backend/auth/me", { credentials: "include" });
		if (res.status === 401) window.location.reload();
	} catch {
		// Offline / backend down — not a sign-out; the next check retries.
	}
}
