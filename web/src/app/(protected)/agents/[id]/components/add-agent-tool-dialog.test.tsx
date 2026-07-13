import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api/client";
import type { MCPServer } from "@/types/mcp-servers";
import AddAgentToolDialog from "./add-agent-tool-dialog";

vi.mock("next/navigation", () => ({
	useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/api/client", () => ({
	api: {
		get: vi.fn(),
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

	it("adds the server to the draft and closes when it was the last one", async () => {
		const user = userEvent.setup();
		const onOpenChange = vi.fn();
		const onAddServer = vi.fn();

		render(
			<AddAgentToolDialog
				open
				onOpenChange={onOpenChange}
				attachedServerIds={[]}
				hasCodeInterpreter={false}
				onAddServer={onAddServer}
				onSandboxToggle={vi.fn()}
			/>,
		);

		await user.click(
			await screen.findByRole("button", { name: "Add Internal Search" }),
		);

		await waitFor(() => {
			expect(onAddServer).toHaveBeenCalledWith("server-1");
			expect(onOpenChange).toHaveBeenCalledWith(false);
		});
	});

	it("hides already-attached servers from the available list", async () => {
		render(
			<AddAgentToolDialog
				open
				onOpenChange={vi.fn()}
				attachedServerIds={["server-1"]}
				hasCodeInterpreter={false}
				onAddServer={vi.fn()}
				onSandboxToggle={vi.fn()}
			/>,
		);

		expect(
			await screen.findByText(
				"All workspace servers are already enabled for this agent.",
			),
		).toBeInTheDocument();
	});
});
