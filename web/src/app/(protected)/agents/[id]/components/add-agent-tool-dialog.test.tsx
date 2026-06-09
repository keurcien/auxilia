import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api/client";
import type { Agent } from "@/types/agents";
import type { MCPServer } from "@/types/mcp-servers";
import AddAgentToolDialog from "./add-agent-tool-dialog";

vi.mock("next/navigation", () => ({
	useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/api/client", () => ({
	api: {
		get: vi.fn(),
		post: vi.fn(),
		patch: vi.fn(),
	},
}));

const availableServer: MCPServer = {
	id: "server-1",
	name: "Internal Search",
	url: "https://search.example.com/mcp",
	authType: "none",
	createdAt: "2026-06-09T00:00:00Z",
	updatedAt: "2026-06-09T00:00:00Z",
};

const agent: Agent = {
	id: "agent-1",
	name: "Researcher",
	instructions: "",
	ownerId: "user-1",
	hasCodeInterpreter: false,
	mcpServers: [],
	subagents: [],
	isSubagent: false,
};

describe("AddAgentToolDialog", () => {
	beforeEach(() => {
		vi.resetAllMocks();
		vi.mocked(api.get).mockImplementation((url) => {
			if (url === "/sandbox/status") {
				return Promise.resolve({ data: { enabled: false } });
			}

			return Promise.resolve({ data: [availableServer] });
		});
	});

	it("closes after assigning the last available MCP server", async () => {
		const user = userEvent.setup();
		const onOpenChange = vi.fn();
		vi.mocked(api.post).mockResolvedValue({ data: {} });

		render(
			<AddAgentToolDialog
				open
				onOpenChange={onOpenChange}
				agent={agent}
			/>,
		);

		await user.click(
			await screen.findByRole("button", { name: "Add Internal Search" }),
		);

		await waitFor(() => {
			expect(api.post).toHaveBeenCalledWith(
				"/agents/agent-1/mcp-servers/server-1",
				{},
			);
			expect(onOpenChange).toHaveBeenCalledWith(false);
		});
	});

	it("stays open when assigning the last available MCP server fails", async () => {
		const user = userEvent.setup();
		const onOpenChange = vi.fn();
		const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
		vi.mocked(api.post).mockRejectedValue(new Error("assignment failed"));

		render(
			<AddAgentToolDialog
				open
				onOpenChange={onOpenChange}
				agent={agent}
			/>,
		);

		await user.click(
			await screen.findByRole("button", { name: "Add Internal Search" }),
		);

		await waitFor(() => expect(api.post).toHaveBeenCalled());
		expect(onOpenChange).not.toHaveBeenCalledWith(false);
		consoleError.mockRestore();
	});
});
