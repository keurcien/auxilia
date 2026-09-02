import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { SubagentDiscoverySnapshot } from "@langchain/langgraph-sdk/stream";
import type { AnyStream } from "@langchain/react";
import { describe, expect, it, vi } from "vitest";

// The card opens scoped selector subscriptions; unit tests stub them out —
// live projections are exercised against the real backend, not jsdom.
vi.mock("@langchain/react", () => ({
	useMessages: () => [],
	useValues: () => undefined,
}));

import { SubAgentCard } from "./subagent";

const stream = {} as AnyStream;

function snapshot(
	overrides: Partial<SubagentDiscoverySnapshot>,
): SubagentDiscoverySnapshot {
	return {
		id: "call_1",
		name: "researcher",
		namespace: ["tools:call_1"],
		parentId: null,
		depth: 1,
		status: "complete",
		taskInput: "Inspect the incident",
		output: undefined,
		error: undefined,
		startedAt: new Date(),
		completedAt: new Date(),
		...overrides,
	};
}

describe("SubAgentCard", () => {
	it("loads restored history only when opened", async () => {
		const onOpen = vi.fn();

		render(
			<SubAgentCard
				subagent={snapshot({})}
				stream={stream}
				onOpen={onOpen}
			/>,
		);

		expect(onOpen).not.toHaveBeenCalled();
		await userEvent.click(screen.getByRole("button"));
		expect(onOpen).toHaveBeenCalledOnce();
	});

	it("loads restored history for an error card that starts open", () => {
		const onOpen = vi.fn();

		render(
			<SubAgentCard
				subagent={snapshot({
					id: "call_2",
					status: "error",
					taskInput: "Inspect the failed task",
					error: "Failed",
					completedAt: new Date(),
				})}
				stream={stream}
				onOpen={onOpen}
			/>,
		);

		expect(onOpen).toHaveBeenCalledOnce();
	});
});
