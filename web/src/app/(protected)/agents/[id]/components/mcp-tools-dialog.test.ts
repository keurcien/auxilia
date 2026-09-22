import { describe, expect, it } from "vitest";
import { buildToolsMarkdown } from "./mcp-tools-dialog";
import { ToolStatus } from "@/types/agents";

describe("buildToolsMarkdown", () => {
	it("renders the server heading, subtitle, and one h2 per tool", () => {
		const statuses = new Map<string, ToolStatus>([
			["run_query", "always_allow"],
			["create_dashboard", "needs_approval"],
			["delete_card", "disabled"],
		]);
		const markdown = buildToolsMarkdown(
			"Metabase",
			[
				{ name: "run_query", description: "Executes a native SQL query." },
				{ name: "create_dashboard", description: "  Create a dashboard.\n" },
				{ name: "delete_card", description: null },
			],
			(name) => statuses.get(name) ?? "always_allow",
		);
		expect(markdown).toBe(
			[
				"# Metabase MCP server",
				"List of all tools available in the MCP server.",
				"## Run query - Always allowed",
				"Executes a native SQL query.",
				"## Create dashboard - Needs approval",
				"Create a dashboard.",
				"## Delete card - Disabled",
			].join("\n\n") + "\n",
		);
	});
});
