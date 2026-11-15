import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import * as agentsApi from "@/lib/api/resources/agents";
import * as threadsApi from "@/lib/api/resources/threads";
import type { Agent } from "@/types/agents";
import type { AgentThread } from "@/types/threads";
import AgentThreadsPage from "./page";

const navigation = vi.hoisted(() => ({
	push: vi.fn(),
	search: "",
}));

vi.mock("next/navigation", () => ({
	useParams: () => ({ id: "agent-1" }),
	useRouter: () => ({ push: navigation.push }),
	useSearchParams: () => new URLSearchParams(navigation.search),
}));

vi.mock("@/lib/api/resources/agents", () => ({
	getAgent: vi.fn(),
}));

vi.mock("@/lib/api/resources/threads", () => ({
	listAgentThreads: vi.fn(),
}));

const agent = {
	id: "agent-1",
	name: "Support bot",
	emoji: null,
	color: null,
	imageRevision: null,
} as unknown as Agent;

function thread(overrides: Partial<AgentThread>): AgentThread {
	return {
		id: "thread-1",
		agentId: "agent-1",
		userId: "user-1",
		firstMessageContent: "How do I reset my password?",
		agentName: "Support bot",
		agentEmoji: null,
		agentColor: null,
		agentArchived: false,
		source: "web",
		createdAt: "2026-11-10T09:30:00Z",
		userName: "Ada Lovelace",
		userEmail: "ada@example.com",
		...overrides,
	};
}

describe("AgentThreadsPage", () => {
	beforeEach(() => {
		vi.resetAllMocks();
		navigation.search = "";
		vi.mocked(agentsApi.getAgent).mockResolvedValue(agent);
	});

	afterEach(() => {
		vi.restoreAllMocks();
	});

	it("lists every user's conversations as links without a minimum table width", async () => {
		vi.mocked(threadsApi.listAgentThreads).mockResolvedValue({
			items: [
				thread({}),
				thread({
					id: "thread-2",
					firstMessageContent: null,
					userName: null,
					userEmail: "grace@example.com",
					source: "slack",
				}),
			],
			total: 2,
			limit: 20,
			offset: 0,
		});

		render(<AgentThreadsPage />);

		const first = await screen.findByRole("link", {
			name: /How do I reset my password\?/,
		});
		expect(first).toHaveAttribute("href", "/agents/agent-1/chat/thread-1");
		expect(within(first).getAllByText("Ada Lovelace").length).toBeGreaterThan(0);

		const second = screen.getByRole("link", { name: /Untitled conversation/ });
		expect(second).toHaveAttribute("href", "/agents/agent-1/chat/thread-2");
		expect(within(second).getAllByText("grace@example.com").length).toBeGreaterThan(0);

		expect(first.closest("[style*='min-width']")).toBeNull();
		expect(threadsApi.listAgentThreads).toHaveBeenCalledWith("agent-1", {
			limit: 20,
			offset: 0,
		});
		expect(
			await screen.findByRole("link", { name: "Back to Support bot" }),
		).toHaveAttribute("href", "/agents/agent-1");
		expect(screen.getByText("1–2")).toBeInTheDocument();
	});

	it("shows the empty state", async () => {
		vi.mocked(threadsApi.listAgentThreads).mockResolvedValue({
			items: [],
			total: 0,
			limit: 20,
			offset: 0,
		});

		render(<AgentThreadsPage />);

		expect(
			await screen.findByText("No conversations with this agent yet."),
		).toBeInTheDocument();
	});

	it("reports a load failure and retries on demand", async () => {
		const user = userEvent.setup();
		vi.mocked(threadsApi.listAgentThreads)
			.mockRejectedValueOnce(new ApiError({ status: 500 }))
			.mockResolvedValueOnce({
				items: [thread({})],
				total: 1,
				limit: 20,
				offset: 0,
			});

		render(<AgentThreadsPage />);

		const alert = await screen.findByRole("alert");
		await user.click(within(alert).getByRole("button", { name: "Retry" }));

		expect(
			await screen.findByRole("link", { name: /How do I reset my password\?/ }),
		).toBeInTheDocument();
		expect(threadsApi.listAgentThreads).toHaveBeenCalledTimes(2);
	});

	it("sends a user without access back to the agent", async () => {
		const user = userEvent.setup();
		vi.mocked(threadsApi.listAgentThreads).mockRejectedValue(
			new ApiError({ status: 403 }),
		);

		render(<AgentThreadsPage />);

		expect(
			await screen.findByText(
				"You don't have permission to view this agent's threads.",
			),
		).toBeInTheDocument();
		await user.click(screen.getAllByRole("button", { name: "Close" })[0]);

		await waitFor(() => {
			expect(navigation.push).toHaveBeenCalledWith("/agents/agent-1");
		});
	});

	it("keeps the page in the URL", async () => {
		const user = userEvent.setup();
		const replaceState = vi.spyOn(window.history, "replaceState");
		navigation.search = "offset=20";
		vi.mocked(threadsApi.listAgentThreads).mockResolvedValue({
			items: [thread({ id: "thread-21" })],
			total: 45,
			limit: 20,
			offset: 20,
		});

		render(<AgentThreadsPage />);

		expect(await screen.findByText("21–40")).toBeInTheDocument();
		expect(threadsApi.listAgentThreads).toHaveBeenCalledWith("agent-1", {
			limit: 20,
			offset: 20,
		});

		await user.click(screen.getByRole("button", { name: "Next page" }));
		const url = replaceState.mock.calls.at(-1)?.[2];
		expect(String(url)).toContain("offset=40");
	});
});
