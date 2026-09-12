import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/errors";
import { callMcpAppTool, readMcpAppResource } from "./mcp-apps";

const json = (data: unknown, status = 200) =>
	new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json" } });

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
	fetchMock = vi.fn().mockResolvedValue(json({ ok: 1 }));
	vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
	vi.unstubAllGlobals();
});

const lastRequest = () => {
	const [url, init] = fetchMock.mock.calls.at(-1) as [string, RequestInit];
	return { url, init, body: JSON.parse(init.body as string) as unknown };
};

describe("mcp-apps resource", () => {
	it("reads a resource on the app's behalf through the protocol transport", async () => {
		expect(await readMcpAppResource("s1", "ui://app/main")).toEqual({ ok: 1 });
		const { url, init, body } = lastRequest();
		expect(url).toBe(`${window.location.origin}/api/backend/mcp-servers/s1/app/read-resource`);
		expect(init.method).toBe("POST");
		expect(init.credentials).toBe("include");
		expect(body).toEqual({ uri: "ui://app/main" });
	});

	it("calls a tool with a snake_case body and returns the payload untouched", async () => {
		fetchMock.mockResolvedValue(
			json({ content: [], structuredContent: { snake_key: 1, nested: { other_key: [1] } }, isError: false }),
		);
		const result = await callMcpAppTool("s1", "search", { q: "x" });
		expect(lastRequest().body).toEqual({ tool_name: "search", arguments: { q: "x" } });
		expect(result.structuredContent).toEqual({ snake_key: 1, nested: { other_key: [1] } });
		await callMcpAppTool("s1", "search", null);
		expect(lastRequest().body).toEqual({ tool_name: "search", arguments: null });
	});

	it("rejects with an ApiError carrying the backend detail", async () => {
		fetchMock.mockResolvedValue(json({ detail: "server unreachable" }, 502));
		const err = await callMcpAppTool("s1", "search", null).catch((e: unknown) => e);
		expect(err).toBeInstanceOf(ApiError);
		expect((err as ApiError).status).toBe(502);
		expect((err as ApiError).detail).toBe("server unreachable");
	});
});
