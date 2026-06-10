import { describe, expect, it } from "vitest";
import { shouldCloseAddToolDialogAfterServerAdded } from "./mcp-server-assignment";

describe("shouldCloseAddToolDialogAfterServerAdded", () => {
	it("closes when the added server was the last available server", () => {
		expect(
			shouldCloseAddToolDialogAfterServerAdded(["server-1"], "server-1"),
		).toBe(true);
	});

	it("stays open when another server remains available", () => {
		expect(
			shouldCloseAddToolDialogAfterServerAdded(
				["server-1", "server-2"],
				"server-1",
			),
		).toBe(false);
	});

	it("stays open when the added server is not in the available list", () => {
		expect(
			shouldCloseAddToolDialogAfterServerAdded(["server-2"], "server-1"),
		).toBe(false);
	});
});
