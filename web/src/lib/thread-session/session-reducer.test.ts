import { describe, expect, it } from "vitest";

import type { Run } from "@/types/runs";
import type { Thread, ThreadRead } from "@/types/threads";
import {
	chatHeaderFromThread,
	initialSessionState,
	lastRunFailed,
	lastRunFallbackMessage,
	pickFailedRunError,
	sessionReducer,
} from "./session-reducer";

const thread = (over: Partial<Thread> = {}): Thread => ({
	id: "t1",
	agentId: "a1",
	userId: "u1",
	firstMessageContent: "Hello",
	agentName: "Helper",
	agentEmoji: "🤖",
	agentColor: "#123456",
	agentArchived: false,
	source: "web",
	createdAt: "2026-09-12T00:00:00Z",
	modelId: "gpt",
	modelAvailable: true,
	...over,
});
const read = (over: Partial<Thread> = {}, viewerRole: ThreadRead["viewerRole"] = null): ThreadRead => ({
	thread: thread(over),
	viewerRole,
});
const run = (status: Run["status"], error: string | null): Run => ({
	id: `r-${status}`,
	threadId: "t1",
	status,
	error,
	createdAt: "",
	updatedAt: "",
});

const opened = sessionReducer(initialSessionState, { type: "opened", threadId: "t1" });

describe("opened", () => {
	it("starts every session-scoped field over for the new thread", () => {
		let s = sessionReducer(opened, { type: "thread-loaded", threadId: "t1", read: read({ modelAvailable: false }) });
		s = sessionReducer(s, { type: "last-run-error-loaded", threadId: "t1", error: "old failure" });
		s = sessionReducer(s, { type: "user-acted" });
		const next = sessionReducer(s, { type: "opened", threadId: "t2" });
		expect(next).toEqual({ ...initialSessionState, threadId: "t2" });
	});

	it("ignores loads that belong to the thread the page left", () => {
		const s = sessionReducer(opened, { type: "opened", threadId: "t2" });
		expect(sessionReducer(s, { type: "thread-loaded", threadId: "t1", read: read() })).toBe(s);
		expect(sessionReducer(s, { type: "last-run-error-loaded", threadId: "t1", error: "late" })).toBe(s);
		expect(sessionReducer(s, { type: "open-failed", threadId: "t1", error: new Error("x") })).toBe(s);
	});
});

describe("open-failed", () => {
	it("marks the session errored and keeps the cause; a later success clears it", () => {
		const failed = sessionReducer(opened, { type: "open-failed", threadId: "t1", error: new Error("offline") });
		expect(failed.meta.status).toBe("error");
		expect((failed.openError as Error).message).toBe("offline");
		const ok = sessionReducer(failed, { type: "thread-loaded", threadId: "t1", read: read() });
		expect(ok.meta.status).toBe("ready");
		expect(ok.openError).toBeNull();
	});
});

describe("thread-loaded", () => {
	it("copies the metadata the page renders on", () => {
		const s = sessionReducer(opened, {
			type: "thread-loaded",
			threadId: "t1",
			read: read({ modelAvailable: false, agentArchived: true }, "admin"),
		});
		expect(s.meta).toMatchObject({
			status: "ready",
			viewerRole: "admin",
			modelAvailable: false,
			agentArchived: true,
		});
		expect(s.meta.thread?.id).toBe("t1");
	});

	it("treats a missing modelAvailable as available", () => {
		const s = sessionReducer(opened, {
			type: "thread-loaded",
			threadId: "t1",
			read: read({ modelAvailable: undefined }),
		});
		expect(s.meta.modelAvailable).toBe(true);
	});
});

describe("the rehydrated error and the stale rule", () => {
	it("shows the last run's error until the user acts", () => {
		let s = sessionReducer(opened, { type: "last-run-error-loaded", threadId: "t1", error: "boom" });
		expect(s.rehydratedError).toBe("boom");
		s = sessionReducer(s, { type: "user-acted" });
		expect(s.rehydratedError).toBeNull();
	});

	it("drops an error that arrives after the user acted (slow fetch)", () => {
		let s = sessionReducer(opened, { type: "user-acted" });
		s = sessionReducer(s, { type: "last-run-error-loaded", threadId: "t1", error: "late" });
		expect(s.rehydratedError).toBeNull();
	});

	it("user-acted is idempotent once the error is cleared", () => {
		const s = sessionReducer(opened, { type: "user-acted" });
		expect(sessionReducer(s, { type: "user-acted" })).toBe(s);
	});
});

describe("model availability", () => {
	it("a 409 gate flips the model unavailable; a recheck can flip it back", () => {
		let s = sessionReducer(opened, { type: "model-unavailable" });
		expect(s.meta.modelAvailable).toBe(false);
		expect(sessionReducer(s, { type: "model-unavailable" })).toBe(s);
		s = sessionReducer(s, { type: "model-rechecked", available: true });
		expect(s.meta.modelAvailable).toBe(true);
	});
});

describe("failed-run helpers", () => {
	it("only error and timeout count as failed, with distinct fallbacks", () => {
		expect(lastRunFailed(thread({ lastRunStatus: "error" }))).toBe(true);
		expect(lastRunFailed(thread({ lastRunStatus: "timeout" }))).toBe(true);
		expect(lastRunFailed(thread({ lastRunStatus: "success" }))).toBe(false);
		expect(lastRunFailed(thread({ lastRunStatus: null }))).toBe(false);
		expect(lastRunFallbackMessage(thread({ lastRunStatus: "timeout" }))).toMatch(/time limit/);
		expect(lastRunFallbackMessage(thread({ lastRunStatus: "error" }))).toMatch(/failed/);
	});

	it("picks the newest failed run's error, else the fallback", () => {
		expect(
			pickFailedRunError([run("success", null), run("error", "tool blew up"), run("error", "older")], "fb"),
		).toBe("tool blew up");
		expect(pickFailedRunError([run("timeout", null)], "fb")).toBe("fb");
		expect(pickFailedRunError([], "fb")).toBe("fb");
	});
});

describe("chatHeaderFromThread", () => {
	it("carries trigger details only for trigger threads", () => {
		expect(chatHeaderFromThread(thread({ triggerId: "tr1" }))).toMatchObject({
			agentName: "Helper",
			modelId: "gpt",
			triggerId: null,
			triggerName: null,
		});
		expect(
			chatHeaderFromThread(thread({ source: "trigger", triggerId: "tr1", firstMessageContent: "Nightly" })),
		).toMatchObject({ triggerId: "tr1", triggerName: "Nightly", triggerRunAt: "2026-09-12T00:00:00Z" });
	});
});
