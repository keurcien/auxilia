import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api/client";
import type { MCPServer } from "@/types/mcp-servers";
import type { Sandbox } from "@/types/sandboxes";
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

const availableSandbox: Sandbox = {
	id: "sandbox-1",
	name: "Data lab",
	description: null,
	provider: "daytona",
	url: "https://app.daytona.io/api",
	config: {},
	hasSecret: true,
	createdAt: "2026-08-22T00:00:00Z",
	updatedAt: "2026-08-22T00:00:00Z",
};

function mockApi({ sandboxes = [availableSandbox] }: { sandboxes?: Sandbox[] } = {}) {
	vi.mocked(api.get).mockImplementation((url) => {
		if (url === "/sandboxes") {
			return Promise.resolve({ data: sandboxes });
		}

		return Promise.resolve({ data: [availableServer] });
	});
}

describe("AddAgentToolDialog", () => {
	beforeEach(() => {
		vi.resetAllMocks();
		mockApi();
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
				attachedSandboxIds={[]}
				onAddServer={onAddServer}
				onAddSandbox={vi.fn()}
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
				attachedSandboxIds={[]}
				onAddServer={vi.fn()}
				onAddSandbox={vi.fn()}
			/>,
		);

		expect(
			await screen.findByText(
				"All workspace servers are already enabled for this agent.",
			),
		).toBeInTheDocument();
	});

	it("adds a sandbox to the draft and closes the dialog", async () => {
		const user = userEvent.setup();
		const onOpenChange = vi.fn();
		const onAddSandbox = vi.fn();

		render(
			<AddAgentToolDialog
				open
				onOpenChange={onOpenChange}
				attachedServerIds={[]}
				attachedSandboxIds={[]}
				onAddServer={vi.fn()}
				onAddSandbox={onAddSandbox}
			/>,
		);

		await user.click(
			await screen.findByRole("button", { name: "Add Data lab" }),
		);

		await waitFor(() => {
			expect(onAddSandbox).toHaveBeenCalledWith("sandbox-1");
			expect(onOpenChange).toHaveBeenCalledWith(false);
		});
	});

	it("hides the sandbox section once one is attached", async () => {
		render(
			<AddAgentToolDialog
				open
				onOpenChange={vi.fn()}
				attachedServerIds={[]}
				attachedSandboxIds={["sandbox-1"]}
				onAddServer={vi.fn()}
				onAddSandbox={vi.fn()}
			/>,
		);

		await screen.findByRole("button", { name: "Add Internal Search" });
		expect(screen.queryByText("SANDBOXES")).not.toBeInTheDocument();
	});
});
