/**
 * Tool-map persistence: the runtime EXCLUDES any tool missing from the saved
 * map (backend toolset.py), so the editor must keep the map complete:
 *
 *  - edit mode: fetched tools are MERGE-seeded into the draft (new tools
 *    added as always_allow, curated statuses preserved, stale keys dropped),
 *    making the form dirty so Save persists them;
 *  - read mode: a successful OAuth connect persists server-side via
 *    POST sync-tools (there is no draft to save after the editor flips back
 *    to read mode on Save).
 */
import { useMemo, useState } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api/client";
import type { MCPServer } from "@/types/mcp-servers";
import type { ToolStatus } from "@/types/agents";
import AgentToolList from "./agent-tool-list";
import {
	AgentFormState,
	AgentMCPServerForm,
	defaultAgentForm,
	isFormDirty,
	toPayload,
} from "../../lib/agent-form";

vi.mock("@/lib/api/client", () => ({
	api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

vi.mock("next/image", () => ({
	default: (props: Record<string, unknown>) => (
		// eslint-disable-next-line jsx-a11y/alt-text, @next/next/no-img-element
		<img {...(props as React.ImgHTMLAttributes<HTMLImageElement>)} />
	),
}));

vi.mock("./add-agent-tool-dialog", () => ({ default: () => null }));

vi.mock("@/components/ai-elements/chain-of-thought", () => ({
	humanizeToolName: (name: string) => name,
}));

const AGENT_ID = "agent-1";

const SERVER: MCPServer = {
	id: "server-1",
	name: "Notion",
	url: "https://notion.example.com/mcp",
	authType: "oauth2",
	createdAt: "2026-08-01T00:00:00Z",
	updatedAt: "2026-08-01T00:00:00Z",
};

/** Minimal stand-in for AgentEditor's form state + save wiring. */
function Harness({
	initialServers,
	readOnly,
	onBindingPersisted,
}: {
	initialServers: AgentMCPServerForm[];
	readOnly: boolean;
	onBindingPersisted?: (
		serverId: string,
		tools: Record<string, ToolStatus>,
	) => void;
}) {
	const initialForm = useMemo<AgentFormState>(
		() => ({ ...defaultAgentForm(), name: "a", mcpServers: initialServers }),
		[initialServers],
	);
	const [form, setForm] = useState(initialForm);
	return (
		<>
			<AgentToolList
				agentId={AGENT_ID}
				readOnly={readOnly}
				mcpServers={form.mcpServers}
				hasCodeInterpreter={false}
				onMcpServersChange={(update) => {
					setForm((prev) => ({
						...prev,
						mcpServers: update(prev.mcpServers),
					}));
				}}
				onBindingPersisted={onBindingPersisted}
			/>
			<output data-testid="dirty">
				{String(!readOnly && isFormDirty(form, initialForm))}
			</output>
			<output data-testid="payload">
				{JSON.stringify(toPayload(form).mcpServers)}
			</output>
		</>
	);
}

function mockApi({
	connected,
	tools,
}: {
	connected: boolean;
	tools: { name: string }[];
}) {
	vi.mocked(api.get).mockImplementation((url: string) => {
		if (url === "/mcp-servers") return Promise.resolve({ data: [SERVER] });
		if (url === `/mcp-servers/${SERVER.id}/is-connected`)
			return Promise.resolve({ data: { connected } });
		if (url === `/mcp-servers/${SERVER.id}/list-tools`)
			return Promise.resolve({ data: tools });
		return Promise.reject(new Error(`unexpected GET ${url}`));
	});
}

async function expandServerCard() {
	const expand = await screen.findByRole("button", { name: "Expand" });
	fireEvent.click(expand);
}

function payload() {
	return screen.getByTestId("payload").textContent ?? "";
}

describe("agent tool map persistence", () => {
	beforeEach(() => {
		vi.resetAllMocks();
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	it("edit mode, never-synced binding: seed fills the draft so Save persists the full map", async () => {
		mockApi({ connected: true, tools: [{ name: "search" }] });
		render(
			<Harness
				readOnly={false}
				initialServers={[{ mcpServerId: SERVER.id, tools: null }]}
			/>,
		);

		await waitFor(() => {
			expect(payload()).toContain('"search":"always_allow"');
		});
		expect(screen.getByTestId("dirty").textContent).toBe("true");
	});

	it("edit mode, server gained a tool: merge-seed adds it, preserves curated statuses, drops stale keys, and dirties the form", async () => {
		mockApi({
			connected: true,
			tools: [{ name: "search" }, { name: "create_page" }],
		});
		render(
			<Harness
				readOnly={false}
				initialServers={[
					{
						mcpServerId: SERVER.id,
						tools: {
							search: "needs_approval",
							removed_tool: "disabled",
						},
					},
				]}
			/>,
		);

		await waitFor(() => {
			expect(payload()).toContain('"create_page":"always_allow"');
		});
		// Curated status preserved, vanished tool dropped.
		expect(payload()).toContain('"search":"needs_approval"');
		expect(payload()).not.toContain("removed_tool");
		// The form is dirty — Save is enabled and the UNSAVED chip shows.
		expect(screen.getByTestId("dirty").textContent).toBe("true");
	});

	it("edit mode, map already current: fetch does not dirty the form", async () => {
		mockApi({ connected: true, tools: [{ name: "search" }] });
		render(
			<Harness
				readOnly={false}
				initialServers={[
					{ mcpServerId: SERVER.id, tools: { search: "needs_approval" } },
				]}
			/>,
		);

		await expandServerCard();
		await screen.findByText("search");
		expect(screen.getByTestId("dirty").textContent).toBe("false");
	});

	it("read mode: OAuth connect persists the map via sync-tools and reports it upward", async () => {
		vi.useFakeTimers();
		let connected = false;
		vi.mocked(api.get).mockImplementation((url: string) => {
			if (url === "/mcp-servers") return Promise.resolve({ data: [SERVER] });
			if (url === `/mcp-servers/${SERVER.id}/is-connected`)
				return Promise.resolve({ data: { connected } });
			if (url === `/mcp-servers/${SERVER.id}/list-tools`) {
				return connected
					? Promise.resolve({ data: [{ name: "search" }] })
					: Promise.reject({
							response: {
								status: 401,
								data: { auth_url: "https://oauth.example.com" },
							},
						});
			}
			return Promise.reject(new Error(`unexpected GET ${url}`));
		});
		vi.mocked(api.post).mockResolvedValue({
			data: {
				agentId: AGENT_ID,
				mcpServerId: SERVER.id,
				tools: { search: "always_allow" },
			},
		});
		const openSpy = vi
			.spyOn(window, "open")
			.mockReturnValue(null as unknown as Window);
		const persisted = vi.fn();

		render(
			<Harness
				readOnly
				initialServers={[{ mcpServerId: SERVER.id, tools: null }]}
				onBindingPersisted={persisted}
			/>,
		);

		// Not-connected cards auto-expand; Connect stays available in read mode.
		const connect = await vi.waitFor(() => {
			const button = screen.queryByRole("button", { name: "Connect" });
			if (!button) throw new Error("Connect not rendered yet");
			return button;
		});
		fireEvent.click(connect);
		await vi.waitFor(() => {
			expect(openSpy).toHaveBeenCalledWith(
				"https://oauth.example.com",
				"_blank",
				"width=600,height=700",
			);
		});

		// User consents in the popup; the next poll tick finds the connection.
		connected = true;
		await vi.advanceTimersByTimeAsync(2000);

		expect(api.post).toHaveBeenCalledWith(
			`/agents/${AGENT_ID}/mcp-servers/${SERVER.id}/sync-tools`,
		);
		expect(persisted).toHaveBeenCalledWith(SERVER.id, {
			search: "always_allow",
		});
	});

	it("read mode: a never-synced binding self-heals on view via sync-tools", async () => {
		mockApi({ connected: true, tools: [{ name: "search" }] });
		vi.mocked(api.post).mockResolvedValue({
			data: {
				agentId: AGENT_ID,
				mcpServerId: SERVER.id,
				tools: { search: "always_allow" },
			},
		});
		const persisted = vi.fn();
		render(
			<Harness
				readOnly
				initialServers={[{ mcpServerId: SERVER.id, tools: null }]}
				onBindingPersisted={persisted}
			/>,
		);

		await waitFor(() => {
			expect(api.post).toHaveBeenCalledWith(
				`/agents/${AGENT_ID}/mcp-servers/${SERVER.id}/sync-tools`,
			);
		});
		expect(persisted).toHaveBeenCalledWith(SERVER.id, {
			search: "always_allow",
		});
	});

	it("read mode: a stale map (server gained a tool, no OAuth involved) self-heals on view", async () => {
		mockApi({
			connected: true,
			tools: [{ name: "search" }, { name: "create_page" }],
		});
		vi.mocked(api.post).mockResolvedValue({
			data: {
				agentId: AGENT_ID,
				mcpServerId: SERVER.id,
				tools: { search: "needs_approval", create_page: "always_allow" },
			},
		});
		const persisted = vi.fn();
		render(
			<Harness
				readOnly
				initialServers={[
					{ mcpServerId: SERVER.id, tools: { search: "needs_approval" } },
				]}
				onBindingPersisted={persisted}
			/>,
		);

		await waitFor(() => {
			expect(api.post).toHaveBeenCalledWith(
				`/agents/${AGENT_ID}/mcp-servers/${SERVER.id}/sync-tools`,
			);
		});
		expect(persisted).toHaveBeenCalledWith(SERVER.id, {
			search: "needs_approval",
			create_page: "always_allow",
		});
	});

	it("read mode: an up-to-date map never writes on view", async () => {
		mockApi({ connected: true, tools: [{ name: "search" }] });
		render(
			<Harness
				readOnly
				initialServers={[
					{ mcpServerId: SERVER.id, tools: { search: "needs_approval" } },
				]}
			/>,
		);

		await expandServerCard();
		await screen.findByText("search");
		expect(api.post).not.toHaveBeenCalled();
	});

	it("shows a CONNECTED pill on connected servers and NOT CONNECTED otherwise", async () => {
		mockApi({ connected: true, tools: [{ name: "search" }] });
		const { unmount } = render(
			<Harness
				readOnly
				initialServers={[{ mcpServerId: SERVER.id, tools: null }]}
			/>,
		);
		const card = (await screen.findByText(SERVER.name)).closest("div");
		expect(await within(card!.parentElement!).findByText("CONNECTED"))
			.toBeInTheDocument();
		unmount();

		mockApi({ connected: false, tools: [] });
		render(
			<Harness
				readOnly
				initialServers={[{ mcpServerId: SERVER.id, tools: null }]}
			/>,
		);
		expect(await screen.findByText("NOT CONNECTED")).toBeInTheDocument();
	});
});
