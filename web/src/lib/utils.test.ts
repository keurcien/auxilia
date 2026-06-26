import { describe, expect, it } from "vitest";
import { cn } from "./utils";

describe("cn", () => {
	it("composes clsx-compatible class values", () => {
		const className = cn(
			"inline-flex",
			["items-center", false && "hidden"],
			{
				"text-sm": true,
				"opacity-50": false,
			},
		);

		expect(className).toBe("inline-flex items-center text-sm");
	});

	it("resolves Tailwind utility conflicts with the last class winning", () => {
		const className = cn(
			"rounded-sm px-2 py-1 text-sm",
			"px-4 text-lg",
			"rounded-lg",
		);

		expect(className).toBe("py-1 px-4 text-lg rounded-lg");
	});
});
