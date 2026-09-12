import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useActiveRunsStore } from "@/stores/active-runs-store";
import { usePendingMessageStore } from "@/stores/pending-message-store";
import type { Run } from "@/types/runs";
import type { Thread, ThreadRead } from "@/types/threads";
import { useThreadSession, type ThreadSessionTransport } from "./use-thread-session";

/**
 * A scripted protocol transport: answers the SDK's hydration reads from
 * fixtures and records every command body. Anything unscripted 404s, so a
 * request this test did not expect shows up as a failure, not a hang.
 */
function scriptedFetch(script: {
	state?: unknown;
	commands?: (body: { method?: string }) => Response | Promise<Response>;
}) {
	const calls: { path: string; body: unknown }[] = [];
	const json = (data: unknown, status = 200) =>
		new Response(JSON.stringify(data), {
			status,
			headers: { "content-type": "application/json" },
		});
	const fetchImpl: typeof fetch = async (input, init) => {
		const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
		const path = new URL(url, "http://localhost").pathname;
		const body = typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : undefined;
		calls.push({ path, body });
		if (path.endsWith("/state")) return json(script.state ?? { values: { messages: [] }, next: [], tasks: [] });
		if (path.endsWith("/history")) return json([]);
		if (path.endsWith("/stream/events"))
			return new Response("", { status: 200, headers: { "content-type": "text/event-stream" } });
		if (path.endsWith("/commands") && script.commands) return script.commands(body as { method?: string });
		return json({ detail: `unscripted ${path}` }, 404);
	};
	return { fetch: fetchImpl, calls };
}

const thread = (over: Partial<Thread> = {}): Thread => ({
	id: "t1",
	agentId: "a1",
	userId: "u1",
	firstMessageContent: "Hello",
	agentName: "Helper",
	agentEmoji: null,
	agentColor: null,
	agentArchived: false,
	source: "web",
	createdAt: "2026-09-12T00:00:00Z",
	modelId: "gpt",
	modelAvailable: true,
	...over,
});

function transportWith(
	read: ThreadRead,
	runs: Run[] | Promise<Run[]> = [],
	fetchScript: Parameters<typeof scriptedFetch>[0] = {},
) {
	const script = scriptedFetch(fetchScript);
	// Nothing is stubbed globally: every request — hydration reads, commands,
	// the live pump — must reach the injected transport.
	vi.stubGlobal("fetch", () => Promise.reject(new Error("global fetch must not be used")));
	const transport: ThreadSessionTransport = {
		fetch: script.fetch,
		readThread: vi.fn().mockResolvedValue(read),
		listThreadRuns: vi.fn().mockImplementation(() => Promise.resolve(runs)),
	};
	return { transport, calls: script.calls };
}

const hydratedState = {
	values: {
		messages: [
			{ type: "human", id: "m1", content: "hi" },
			{ type: "ai", id: "m2", content: "hello", tool_calls: [] },
		],
	},
	next: [],
	tasks: [],
};

beforeEach(() => {
	useActiveRunsStore.setState(useActiveRunsStore.getInitialState(), true);
	usePendingMessageStore.setState({ pendingMessages: new Map() });
});
afterEach(() => {
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

describe("useThreadSession", () => {
	it("loads the thread metadata and hydrates the transcript through the injected transport", async () => {
		const { transport, calls } = transportWith(
			{ thread: thread({ agentArchived: true }), viewerRole: "admin" },
			[],
			{ state: hydratedState },
		);
		const { result } = renderHook(() => useThreadSession({ threadId: "t1", agentId: "a1", transport }));

		await waitFor(() => {
			expect(result.current.meta.status).toBe("ready");
		});
		expect(result.current.meta).toMatchObject({ viewerRole: "admin", agentArchived: true, modelAvailable: true });
		expect(transport.readThread).toHaveBeenCalledWith("t1");

		await waitFor(() => {
			expect(result.current.transcript.messages).toHaveLength(2);
		});
		expect(calls.some((c) => c.path === "/api/backend/threads/t1/state")).toBe(true);
		expect(result.current.run).toMatchObject({ status: "idle", isLoading: false, rehydratedError: null });
	});

	it("rehydrates the last failed run's error, and drops it once the user acts", async () => {
		const { transport } = transportWith(
			{ thread: thread({ lastRunStatus: "error" }), viewerRole: null },
			[{ id: "r1", threadId: "t1", status: "error", error: "tool blew up", createdAt: "", updatedAt: "" }],
			{
				commands: () => new Response(JSON.stringify({ detail: "nope" }), { status: 500 }),
			},
		);
		const { result } = renderHook(() => useThreadSession({ threadId: "t1", agentId: "a1", transport }));

		await waitFor(() => {
			expect(result.current.run.rehydratedError).toBe("tool blew up");
		});

		act(() => {
			result.current.actions.send({ text: "again", files: [] });
		});
		expect(result.current.run.rehydratedError).toBeNull();
	});

	it("a slow runs fetch cannot resurrect the error after the user acted", async () => {
		let resolveRuns!: (runs: Run[]) => void;
		const runs = new Promise<Run[]>((r) => {
			resolveRuns = r;
		});
		const { transport } = transportWith(
			{ thread: thread({ lastRunStatus: "timeout" }), viewerRole: null },
			runs,
			{ commands: () => new Response("{}", { status: 500 }) },
		);
		const { result } = renderHook(() => useThreadSession({ threadId: "t1", agentId: "a1", transport }));
		await waitFor(() => {
			expect(result.current.meta.status).toBe("ready");
		});

		act(() => {
			result.current.actions.send({ text: "go", files: [] });
		});
		await act(async () => {
			resolveRuns([]);
			await Promise.resolve();
		});
		expect(result.current.run.rehydratedError).toBeNull();
	});

	it("submits a parked first message exactly once, after hydration", async () => {
		usePendingMessageStore.getState().setPendingMessage("t1", { text: "first!", files: [] });
		const { transport, calls } = transportWith(
			{ thread: thread(), viewerRole: null },
			[],
			{ commands: () => new Response("{}", { status: 500 }) },
		);
		renderHook(() => useThreadSession({ threadId: "t1", agentId: "a1", transport, pendingMessageCapMs: 50 }));

		await waitFor(() => {
			expect(calls.filter((c) => (c.body as { method?: string })?.method === "run.start")).toHaveLength(1);
		});
		const start = calls.find((c) => (c.body as { method?: string })?.method === "run.start")!;
		expect(JSON.stringify(start.body)).toContain("first!");
		expect(usePendingMessageStore.getState().pendingMessages.size).toBe(0);
		// a run.start marks the thread running for the sidebar
		expect(Object.keys(useActiveRunsStore.getState().optimisticMarkedAt)).toEqual(["t1"]);
	});

	it("a model_unavailable rejection locks the model and surfaces the error", async () => {
		const { transport } = transportWith({ thread: thread(), viewerRole: null }, [], {
			commands: () =>
				new Response(JSON.stringify({ error: "model_unavailable", model_id: "gpt", detail: "disabled by admin" }), {
					status: 409,
					headers: { "content-type": "application/json" },
				}),
		});
		const { result } = renderHook(() => useThreadSession({ threadId: "t1", agentId: "a1", transport }));
		await waitFor(() => {
			expect(result.current.meta.status).toBe("ready");
		});

		act(() => {
			result.current.actions.send({ text: "hi", files: [] });
		});
		await waitFor(() => {
			expect(result.current.meta.modelAvailable).toBe(false);
		});
		await waitFor(() => {
			expect(result.current.run.error).toBeInstanceOf(Error);
		});
		expect((result.current.run.error as Error).name).toBe("ModelUnavailableError");
	});

	it("recheckModel re-reads the thread and lifts the lock when the model is back", async () => {
		const { transport } = transportWith({ thread: thread({ modelAvailable: false }), viewerRole: null });
		const { result } = renderHook(() => useThreadSession({ threadId: "t1", agentId: "a1", transport }));
		await waitFor(() => {
			expect(result.current.meta.modelAvailable).toBe(false);
		});
		vi.mocked(transport.readThread).mockResolvedValue({ thread: thread({ modelAvailable: true }), viewerRole: null });
		await act(async () => {
			await result.current.actions.recheckModel();
		});
		expect(result.current.meta.modelAvailable).toBe(true);
	});

	it("stop() asks the sidebar poller to refresh", async () => {
		const { transport } = transportWith({ thread: thread(), viewerRole: null });
		const { result } = renderHook(() => useThreadSession({ threadId: "t1", agentId: "a1", transport }));
		await waitFor(() => {
			expect(result.current.meta.status).toBe("ready");
		});
		const before = useActiveRunsStore.getState().pollEpoch;
		act(() => {
			result.current.actions.stop();
		});
		expect(useActiveRunsStore.getState().pollEpoch).toBe(before + 1);
	});
});
