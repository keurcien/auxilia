import { afterEach, describe, expect, it, vi } from "vitest";

import { ensureSignedIn } from "@/lib/api/session";

function setup(path: string, status: number) {
	const reload = vi.fn();
	vi.stubGlobal("location", { pathname: path, reload });
	vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status })));
	return reload;
}

describe("ensureSignedIn", () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it("reloads into the sign-in redirect when the session is gone", async () => {
		const reload = setup("/agents/1/chat", 401);
		await ensureSignedIn();
		expect(reload).toHaveBeenCalledOnce();
	});

	it("shares one check across a burst of 401s", async () => {
		const reload = setup("/agents/1/chat", 401);
		await Promise.all([ensureSignedIn(), ensureSignedIn(), ensureSignedIn()]);
		expect(fetch).toHaveBeenCalledOnce();
		expect(reload).toHaveBeenCalledOnce();
	});

	it("stays put when the session is still valid", async () => {
		const reload = setup("/agents/1/chat", 200);
		await ensureSignedIn();
		expect(reload).not.toHaveBeenCalled();
	});

	it("never checks on public pages (bad-password 401s)", async () => {
		const reload = setup("/auth", 401);
		await ensureSignedIn();
		expect(fetch).not.toHaveBeenCalled();
		expect(reload).not.toHaveBeenCalled();
	});
});
