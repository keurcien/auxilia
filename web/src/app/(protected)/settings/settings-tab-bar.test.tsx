import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SettingsTabBar, settingsTabBarItems } from "./settings-tab-bar";

describe("settingsTabBarItems", () => {
	it("covers every profile section for any user", () => {
		const items = settingsTabBarItems({
			tab: "profile",
			profileSection: "memories",
			isAdmin: false,
		});

		expect(items.map((item) => item.key)).toEqual([
			"information",
			"security",
			"preferences",
			"threads",
			"memories",
			"connected-accounts",
			"tokens",
		]);
		expect(items.filter((item) => item.active).map((item) => item.key)).toEqual([
			"memories",
		]);
		expect(items.find((item) => item.key === "memories")?.href).toBe(
			"/settings?tab=profile&section=memories",
		);
	});

	it("lists workspace settings for admins only", () => {
		expect(
			settingsTabBarItems({ tab: "models", profileSection: "information", isAdmin: false }),
		).toEqual([]);

		const items = settingsTabBarItems({
			tab: "sandboxes",
			profileSection: "information",
			isAdmin: true,
		});
		expect(items.map((item) => item.key)).toEqual([
			"models",
			"authentication",
			"messaging",
			"observability",
			"sandboxes",
			"appearance",
		]);
		expect(items.find((item) => item.active)?.href).toBe("/settings?tab=sandboxes");
	});
});

describe("SettingsTabBar", () => {
	it("exposes full names, deep links and the current tab", () => {
		render(
			<SettingsTabBar
				label="Profile sections"
				items={settingsTabBarItems({
					tab: "profile",
					profileSection: "preferences",
					isAdmin: false,
				})}
			/>,
		);

		const nav = screen.getByRole("navigation", { name: "Profile sections" });
		const links = within(nav).getAllByRole("link");
		expect(links).toHaveLength(7);

		const current = within(nav).getByRole("link", { name: "Preferences" });
		expect(current).toHaveAttribute("aria-current", "page");
		expect(current).toHaveAttribute(
			"href",
			"/settings?tab=profile&section=preferences",
		);
		expect(within(nav).getByText("Options")).toBeInTheDocument();
		expect(
			within(nav).getByRole("link", { name: "Connected accounts" }),
		).not.toHaveAttribute("aria-current");
		expect(links.filter((link) => link.hasAttribute("aria-current"))).toHaveLength(1);
	});

	it("is hidden on desktop and renders nothing without tabs", () => {
		const { container, rerender } = render(
			<SettingsTabBar label="Settings sections" items={[]} />,
		);
		expect(container).toBeEmptyDOMElement();

		rerender(
			<SettingsTabBar
				label="Settings sections"
				items={settingsTabBarItems({
					tab: "models",
					profileSection: "information",
					isAdmin: true,
				})}
			/>,
		);
		expect(screen.getByRole("navigation", { name: "Settings sections" })).toHaveClass(
			"lg:hidden",
			"pb-[env(safe-area-inset-bottom)]",
		);
	});
});
