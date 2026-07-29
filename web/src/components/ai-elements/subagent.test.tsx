import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { SubagentStreamInterface } from "@langchain/langgraph-sdk/ui";
import { describe, expect, it, vi } from "vitest";

import { SubAgentCard } from "./subagent";


describe("SubAgentCard", () => {
	it("loads restored history only when opened", async () => {
		const onOpen = vi.fn();
		const subagent = {
			id: "call_1",
			status: "complete",
			toolCall: { args: { description: "Inspect the incident" } },
			messages: [],
			values: {},
		} as unknown as SubagentStreamInterface<
			Record<string, unknown>,
			Record<string, unknown>,
			string
		>;

		render(<SubAgentCard subagent={subagent} onOpen={onOpen} />);

		expect(onOpen).not.toHaveBeenCalled();
		await userEvent.click(screen.getByRole("button"));
		expect(onOpen).toHaveBeenCalledOnce();
	});

	it("loads restored history for an error card that starts open", () => {
		const onOpen = vi.fn();
		const subagent = {
			id: "call_2",
			status: "error",
			toolCall: { args: { description: "Inspect the failed task" } },
			messages: [],
			values: {},
			error: "Failed",
		} as unknown as SubagentStreamInterface<
			Record<string, unknown>,
			Record<string, unknown>,
			string
		>;

		render(<SubAgentCard subagent={subagent} onOpen={onOpen} />);

		expect(onOpen).toHaveBeenCalledOnce();
	});
});
