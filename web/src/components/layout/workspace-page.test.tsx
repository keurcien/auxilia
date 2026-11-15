import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { BreadcrumbSegment } from "./subpage-header";
import { WorkspacePage } from "./workspace-page";

function renderPage(fillHeight?: boolean, parents?: BreadcrumbSegment[]) {
	render(
		<WorkspacePage
			slug="triggers"
			parents={parents}
			title="Triggers"
			intro="Run agents automatically."
			fillHeight={fillHeight}
		>
			<p>List content</p>
		</WorkspacePage>,
	);
	const scrollArea = screen
		.getByText("List content")
		.closest("[data-workspace-scroll]");
	if (!(scrollArea instanceof HTMLElement)) {
		throw new Error("Missing workspace scroll area");
	}
	return scrollArea;
}

function classes(element: Element): string[] {
	return element.className.split(/\s+/);
}

describe("WorkspacePage", () => {
	it("scrolls the page in one positioned container", () => {
		const scrollArea = renderPage();

		expect(classes(scrollArea)).toEqual(
			expect.arrayContaining(["relative", "min-h-0", "flex-1", "overflow-y-auto"]),
		);
		expect(classes(scrollArea)).not.toContain("overflow-hidden");
	});

	it("pins fill-height pages only on tall viewports", () => {
		const scrollArea = renderPage(true);

		expect(classes(scrollArea)).toEqual(
			expect.arrayContaining(["relative", "overflow-y-auto", "tall:overflow-hidden"]),
		);
		expect(classes(scrollArea)).not.toContain("overflow-hidden");
		const pinned = scrollArea.querySelectorAll(".tall\\:flex-1");
		expect(pinned).toHaveLength(2);
		pinned.forEach((element) => {
			expect(classes(element)).not.toContain("flex-1");
			expect(classes(element)).toContain("tall:min-h-0");
		});
	});

	it("links parent breadcrumb segments and keeps the safe area clear", () => {
		const scrollArea = renderPage(false, [
			{ label: "agents", href: "/agents" },
			{ label: "Support bot", href: "/agents/agent-1" },
		]);

		const crumbs = screen.getByRole("navigation");
		expect(crumbs).toHaveTextContent("workspace/agents/Support bot/triggers");
		expect(screen.getByRole("link", { name: "agents" })).toHaveAttribute(
			"href",
			"/agents",
		);
		expect(screen.getByRole("link", { name: "Support bot" })).toHaveAttribute(
			"href",
			"/agents/agent-1",
		);
		expect(scrollArea.firstElementChild).toHaveClass(
			"pb-[calc(2.5rem+env(safe-area-inset-bottom))]",
		);
	});
});
