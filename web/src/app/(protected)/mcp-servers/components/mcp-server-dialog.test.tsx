import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api/client";
import { useMcpServersStore } from "@/stores/mcp-servers-store";
import type { MCPServer } from "@/types/mcp-servers";
import MCPServerDialog from "./mcp-server-dialog";

vi.mock("@/lib/api/client", () => ({
	api: {
		get: vi.fn(),
		post: vi.fn(),
		patch: vi.fn(),
		delete: vi.fn(),
	},
}));

const createdServer: MCPServer = {
	id: "server-1",
	name: "Internal Search",
	url: "https://search.example.com/mcp",
	authType: "api_key",
	createdAt: "2026-05-25T00:00:00Z",
	updatedAt: "2026-05-25T00:00:00Z",
};

describe("MCPServerDialog create mode", () => {
	beforeEach(() => {
		vi.resetAllMocks();
		useMcpServersStore.setState({
			mcpServers: [],
			isInitialized: false,
		});
		vi.mocked(api.get).mockResolvedValue({ data: [] });
	});

	it("creates a custom API-key server, publishes it to the store, and closes", async () => {
		const user = userEvent.setup();
		const onOpenChange = vi.fn();
		vi.mocked(api.post).mockResolvedValue({ data: createdServer });

		render(<MCPServerDialog open onOpenChange={onOpenChange} />);

		await user.type(screen.getByLabelText("Name"), createdServer.name);
		await user.type(
			screen.getByLabelText(/Remote Server Address/),
			createdServer.url,
		);
		await user.click(screen.getByLabelText("Authentication Method"));
		await user.click(await screen.findByRole("menuitem", { name: "API Key" }));
		await user.type(screen.getByLabelText("API Key"), "secret-token");
		await user.click(screen.getByRole("button", { name: "Create server" }));

		await waitFor(() => {
			expect(api.post).toHaveBeenCalledWith("/mcp-servers", {
				name: "Internal Search",
				url: "https://search.example.com/mcp",
				authType: "api_key",
				description: undefined,
				iconUrl: undefined,
				apiKey: "secret-token",
				oauthClientId: undefined,
				oauthClientSecret: undefined,
			});
		});
		expect(useMcpServersStore.getState().mcpServers).toEqual([createdServer]);
		expect(onOpenChange).toHaveBeenCalledWith(false);
	});

	it("surfaces a fallback error, keeps the dialog open, and does not publish on failure", async () => {
		const user = userEvent.setup();
		const onOpenChange = vi.fn();
		vi.mocked(api.post).mockRejectedValue(new Error("network down"));

		render(<MCPServerDialog open onOpenChange={onOpenChange} />);

		await user.type(screen.getByLabelText("Name"), "Internal Search");
		await user.type(
			screen.getByLabelText(/Remote Server Address/),
			"https://search.example.com/mcp",
		);
		await user.click(screen.getByRole("button", { name: "Create server" }));

		await waitFor(() => expect(api.post).toHaveBeenCalled());
		expect(
			await screen.findByText("Failed to create MCP server."),
		).toBeInTheDocument();
		await waitFor(() =>
			expect(
				screen.getByRole("button", { name: "Create server" }),
			).toBeEnabled(),
		);
		expect(useMcpServersStore.getState().mcpServers).toEqual([]);
		expect(onOpenChange).not.toHaveBeenCalledWith(false);
	});

	it("surfaces the backend error detail when creation is rejected", async () => {
		const user = userEvent.setup();
		const onOpenChange = vi.fn();
		vi.mocked(api.post).mockRejectedValue({
			status: 400,
			response: { data: { detail: "An MCP server with this URL already exists" } },
		});

		render(<MCPServerDialog open onOpenChange={onOpenChange} />);

		await user.type(screen.getByLabelText("Name"), "Internal Search");
		await user.type(
			screen.getByLabelText(/Remote Server Address/),
			"https://search.example.com/mcp",
		);
		await user.click(screen.getByRole("button", { name: "Create server" }));

		expect(
			await screen.findByText("An MCP server with this URL already exists"),
		).toBeInTheDocument();
		expect(onOpenChange).not.toHaveBeenCalledWith(false);
	});

	it("hides 5xx detail and shows the generic fallback instead", async () => {
		const user = userEvent.setup();
		const onOpenChange = vi.fn();
		vi.mocked(api.post).mockRejectedValue({
			status: 500,
			response: { data: { detail: "psycopg.errors.UndefinedColumn: ..." } },
		});

		render(<MCPServerDialog open onOpenChange={onOpenChange} />);

		await user.type(screen.getByLabelText("Name"), "Internal Search");
		await user.type(
			screen.getByLabelText(/Remote Server Address/),
			"https://search.example.com/mcp",
		);
		await user.click(screen.getByRole("button", { name: "Create server" }));

		expect(
			await screen.findByText("Failed to create MCP server."),
		).toBeInTheDocument();
		expect(
			screen.queryByText(/psycopg/),
		).not.toBeInTheDocument();
	});
});
