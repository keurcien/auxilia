import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
	McpOAuthProvider,
	useMcpOAuth,
} from "@/components/providers/mcp-oauth-provider";
import * as mcpServersApi from "@/lib/api/resources/mcp-servers";

vi.mock("@/lib/api/resources/mcp-servers", () => ({
	completeManualOAuth: vi.fn(),
}));

vi.mock("sonner", () => ({
	toast: {
		error: vi.fn(),
		success: vi.fn(),
	},
}));

function Harness({ onSuccess = vi.fn() }: { onSuccess?: () => void }) {
	const { startAuthorization } = useMcpOAuth();
	return (
		<>
			<button
				type="button"
				onClick={() => {
					startAuthorization({
						authUrl: "https://auth.frame.io/authorize?state=state-1",
						redirectMode: "loopback_manual",
						serverId: "server-1",
						serverName: "Frame.io",
						onSuccess,
					});
				}}
			>
				Connect manually
			</button>
			<button
				type="button"
				onClick={() => {
					startAuthorization({
						authUrl: "https://oauth.example.com/authorize",
						redirectMode: "hosted_callback",
					});
				}}
			>
				Connect hosted
			</button>
		</>
	);
}

describe("McpOAuthProvider", () => {
	const close = vi.fn();
	const popup = {
		closed: false,
		close,
		location: { href: "" },
	} as unknown as Window;

	beforeEach(() => {
		vi.resetAllMocks();
		Object.defineProperty(window, "open", {
			configurable: true,
			value: vi.fn(() => popup),
		});
	});

	it("opens manual authorization and completes from the pasted loopback URL", async () => {
		const user = userEvent.setup();
		const onSuccess = vi.fn();
		vi.mocked(mcpServersApi.completeManualOAuth).mockResolvedValue({
			success: true,
			serverId: "server-1",
			serverName: "Frame.io",
		});
		render(
			<McpOAuthProvider>
				<Harness onSuccess={onSuccess} />
			</McpOAuthProvider>,
		);

		await user.click(screen.getByRole("button", { name: "Connect manually" }));

		expect(
			screen.getByRole("heading", {
				name: "Authentication is almost complete",
			}),
		).toBeInTheDocument();
		expect(screen.getByText(/cannot connect to 127\.0\.0\.1/)).toBeInTheDocument();
		expect(screen.getByText(/do not share it/i)).toBeInTheDocument();

		const callbackUrl =
			"http://127.0.0.1:4789/oauth/callback?code=code-1&state=state-1";
		await user.type(screen.getByLabelText("Browser address"), callbackUrl);
		await user.click(screen.getByRole("button", { name: "Finish connection" }));

		await waitFor(() => {
			expect(mcpServersApi.completeManualOAuth).toHaveBeenCalledWith(callbackUrl);
		});
		expect(onSuccess).toHaveBeenCalledWith({
			success: true,
			serverId: "server-1",
			serverName: "Frame.io",
		});
		await waitFor(() => {
			expect(
				screen.queryByRole("heading", {
					name: "Authentication is almost complete",
				}),
			).not.toBeInTheDocument();
		});
		expect(close).toHaveBeenCalled();
	});

	it("keeps the hosted callback flow free of the manual modal", async () => {
		const user = userEvent.setup();
		render(
			<McpOAuthProvider>
				<Harness />
			</McpOAuthProvider>,
		);

		await user.click(screen.getByRole("button", { name: "Connect hosted" }));

		expect(window.open).toHaveBeenCalled();
		expect(
			screen.queryByRole("heading", {
				name: "Authentication is almost complete",
			}),
		).not.toBeInTheDocument();
	});
});
