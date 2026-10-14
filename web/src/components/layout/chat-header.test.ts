import { describe, expect, it } from "vitest";
import { formatExactCost, formatPillCost } from "./chat-header";

describe("formatPillCost", () => {
	it("rounds to two decimals and reserves room for hundreds", () => {
		expect(formatPillCost("0.0100")).toBe("0.01$");
		expect(formatPillCost("1.235")).toBe("1.24$");
		expect(formatPillCost("123.4")).toBe("123.40$");
	});

	it("shows < 0.01$ under a cent, but not for zero", () => {
		expect(formatPillCost("0.004466")).toBe("<\u20090.01$");
		expect(formatPillCost("0")).toBe("0.00$");
	});
});

describe("formatExactCost", () => {
	it("keeps the exact decimal and drops trailing zeros", () => {
		expect(formatExactCost("0.0012000")).toBe("0.0012$");
		expect(formatExactCost("2.000")).toBe("2$");
		expect(formatExactCost("15")).toBe("15$");
		expect(formatExactCost("0E-7")).toBe("0$");
		expect(formatExactCost("5E-7")).toBe("0.0000005$");
	});
});
