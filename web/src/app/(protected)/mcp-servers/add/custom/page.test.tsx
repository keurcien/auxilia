import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api/client";
import { useMcpServersStore } from "@/stores/mcp-servers-store";
import type { MCPServer } from "@/types/mcp-servers";
import CustomMCPServerPage from "./page";

const { push } = vi.hoisted(() => ({ push: vi.fn() }));

vi.mock("next/navigation", () => ({
	useRouter: () => ({ push }),
	useSearchParams: () => new URLSearchParams(),
}));

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

async function fillRequiredFields(user: ReturnType<typeof userEvent.setup>) {
	await user.type(screen.getByLabelText(/^Name/), createdServer.name);
	await user.type(
		screen.getByLabelText(/Remote server address/),
		createdServer.url,
	);
}

describe("CustomMCPServerPage", () => {
	beforeEach(() => {
		vi.resetAllMocks();
		useMcpServersStore.setState({
			mcpServers: [],
			isInitialized: false,
		});
		vi.mocked(api.get).mockResolvedValue({ data: [] });
	});

	it("creates a custom API-key server, publishes it to the store, and navigates back", async () => {
		const user = userEvent.setup();
		vi.mocked(api.post).mockResolvedValue({ data: createdServer });

		render(<CustomMCPServerPage />);

		await fillRequiredFields(user);
		await user.click(screen.getByRole("radio", { name: /API key/ }));
		await user.type(screen.getByLabelText(/^API key/), "secret-token");
		await user.click(screen.getByRole("button", { name: "Add server" }));

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
		expect(push).toHaveBeenCalledWith("/mcp-servers");
	});

	it("surfaces a fallback error, stays on the page, and does not publish on failure", async () => {
		const user = userEvent.setup();
		vi.mocked(api.post).mockRejectedValue(new Error("network down"));

		render(<CustomMCPServerPage />);

		await fillRequiredFields(user);
		await user.click(screen.getByRole("button", { name: "Add server" }));

		await waitFor(() => {
			expect(api.post).toHaveBeenCalled();
		});
		expect(
			await screen.findByText("Failed to create MCP server."),
		).toBeInTheDocument();
		await waitFor(() => {
			expect(screen.getByRole("button", { name: "Add server" })).toBeEnabled();
		});
		expect(useMcpServersStore.getState().mcpServers).toEqual([]);
		expect(push).not.toHaveBeenCalled();
	});

	it("surfaces the backend error detail when creation is rejected", async () => {
		const user = userEvent.setup();
		vi.mocked(api.post).mockRejectedValue({
			status: 409,
			response: { data: { detail: "An MCP server with this URL already exists" } },
		});

		render(<CustomMCPServerPage />);

		await fillRequiredFields(user);
		await user.click(screen.getByRole("button", { name: "Add server" }));

		expect(
			await screen.findByText("An MCP server with this URL already exists"),
		).toBeInTheDocument();
		expect(push).not.toHaveBeenCalled();
	});

	it("hides 5xx detail and shows the generic fallback instead", async () => {
		const user = userEvent.setup();
		vi.mocked(api.post).mockRejectedValue({
			status: 500,
			response: { data: { detail: "psycopg.errors.UndefinedColumn: ..." } },
		});

		render(<CustomMCPServerPage />);

		await fillRequiredFields(user);
		await user.click(screen.getByRole("button", { name: "Add server" }));

		expect(
			await screen.findByText("Failed to create MCP server."),
		).toBeInTheDocument();
		expect(screen.queryByText(/psycopg/)).not.toBeInTheDocument();
	});
});
