import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useActiveRunsStore } from "@/stores/active-runs-store";
import { useProtocolFetch } from "./use-protocol-fetch";

const json = (data: unknown, status = 200) =>
	new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json" } });
const command = (method: string) => ({ method: "POST", body: JSON.stringify({ method, params: {} }) });

function mount(baseFetch: typeof fetch, handlers: { onModelUnavailable?: () => void; onStaleInterrupt?: () => void } = {}) {
	const { result } = renderHook(() => useProtocolFetch("t1", { baseFetch, ...handlers }));
	return result.current;
}

beforeEach(() => {
	useActiveRunsStore.setState(useActiveRunsStore.getInitialState(), true);
});

describe("useProtocolFetch", () => {
	it("marks the thread running on run.start and passes the response through", async () => {
		const base = vi.fn().mockResolvedValue(json({ ok: true }));
		const f = mount(base);
		const res = await f("/api/backend/threads/t1/commands", command("run.start"));
		expect(res.status).toBe(200);
		expect(base).toHaveBeenCalledWith("/api/backend/threads/t1/commands", command("run.start"));
		expect(Object.keys(useActiveRunsStore.getState().optimisticMarkedAt)).toEqual(["t1"]);
	});

	it("asks for a poll when run.start fails, so the optimistic mark is reconciled", async () => {
		const base = vi.fn().mockResolvedValue(json({ detail: "boom" }, 500));
		const f = mount(base);
		const before = useActiveRunsStore.getState().pollEpoch;
		await f("/x", command("run.start"));
		// markThreadRunning bumps once, the failure bumps again
		expect(useActiveRunsStore.getState().pollEpoch).toBe(before + 2);
	});

	it("does not touch run bookkeeping for reads or other commands", async () => {
		const base = vi.fn().mockResolvedValue(json({}));
		const f = mount(base);
		await f("/api/backend/threads/t1/state");
		await f("/x", command("input.respond"));
		expect(useActiveRunsStore.getState().optimisticMarkedAt).toEqual({});
		expect(useActiveRunsStore.getState().pollEpoch).toBe(0);
	});

	it("decodes a model_unavailable 409: handler, then a named error for the stream stack", async () => {
		const onModelUnavailable = vi.fn();
		const base = vi.fn().mockResolvedValue(json({ error: "model_unavailable", model_id: "m", detail: "disabled" }, 409));
		const f = mount(base, { onModelUnavailable });
		await expect(f("/x", command("run.start"))).rejects.toMatchObject({
			name: "ModelUnavailableError",
			message: "disabled",
		});
		expect(onModelUnavailable).toHaveBeenCalledTimes(1);
	});

	it("decodes a stale_interrupt 409 the same way", async () => {
		const onStaleInterrupt = vi.fn();
		const base = vi.fn().mockResolvedValue(json({ error: "stale_interrupt", detail: "already handled" }, 409));
		const f = mount(base, { onStaleInterrupt });
		await expect(f("/x", command("input.respond"))).rejects.toMatchObject({ name: "StaleInterruptError" });
		expect(onStaleInterrupt).toHaveBeenCalledTimes(1);
	});

	it("lets an unknown 409 through untouched", async () => {
		const base = vi.fn().mockResolvedValue(json({ detail: "some other conflict" }, 409));
		const f = mount(base);
		const res = await f("/x", command("run.start"));
		expect(res.status).toBe(409);
		expect(await res.json()).toEqual({ detail: "some other conflict" });
	});
});
