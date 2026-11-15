import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PageShell } from "./page-shell";

const navigation = vi.hoisted(() => ({ pathname: "/" }));

vi.mock("next/navigation", () => ({
	usePathname: () => navigation.pathname,
}));
vi.mock("@/components/layout/chat-header", () => ({
	ChatHeader: () => null,
}));
vi.mock("@/components/layout/supervision-banner", () => ({
	SupervisionBanner: () => null,
}));
vi.mock("@/components/ui/sidebar", () => ({
	SidebarTrigger: () => null,
}));

describe("PageShell", () => {
	beforeEach(() => {
		navigation.pathname = "/";
	});

	it.each([
		["chat", "/agents/agent-1/chat/thread-1"],
		["workspace list", "/triggers"],
		["workspace list", "/agents"],
		["agent thread history", "/agents/agent-1/threads"],
		["default page", "/notifications"],
	])("contains absolutely positioned content on a %s route", (_, pathname) => {
		navigation.pathname = pathname;
		render(
			<PageShell>
				<span className="sr-only">Row action</span>
			</PageShell>,
		);

		expect(screen.getByRole("main")).toHaveClass("relative", "overflow-hidden");
	});

	it("positions the default scroll container", () => {
		navigation.pathname = "/notifications";
		render(
			<PageShell>
				<p>Page content</p>
			</PageShell>,
		);

		const scroller = screen.getByText("Page content").parentElement;
		expect(scroller).toHaveClass("relative", "overflow-y-auto");
	});

	it("lets the agent thread history own its scroll area", () => {
		navigation.pathname = "/agents/agent-1/threads";
		render(
			<PageShell>
				<p>History</p>
			</PageShell>,
		);

		const wrapper = screen.getByText("History").parentElement;
		expect(wrapper).toHaveClass("overflow-hidden");
		expect(wrapper).not.toHaveClass("overflow-y-auto");
	});
});
