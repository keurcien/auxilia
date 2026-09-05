import { AIMessage, HumanMessage, ToolMessage } from "@langchain/core/messages";
import type { AssembledToolCall } from "@langchain/react";
import { describe, expect, it } from "vitest";
import {
  extractHitlToolNames,
  findSubagentInterrupt,
  getMcpAppInfo,
  getReasoning,
  getToolStepState,
  groupChains,
  pairToolCalls,
  splitInterrupts,
} from "./message-helpers";

const ai = (id: string, calls: { id: string; name: string; args?: object }[], text = "") =>
  new AIMessage({
    id,
    content: text,
    tool_calls: calls.map((c) => ({ ...c, args: c.args ?? {}, type: "tool_call" as const })),
  });

const handle = (over: Partial<AssembledToolCall>): AssembledToolCall => ({
  id: "c1",
  callId: "c1",
  name: "search",
  namespace: [],
  input: {},
  args: {},
  output: null,
  status: "running",
  error: undefined,
  ...over,
});

describe("pairToolCalls", () => {
  it("pairs a call with its ToolMessage from the log", () => {
    const [tc] = pairToolCalls([
      ai("a1", [{ id: "c1", name: "search", args: { q: "x" } }]),
      new ToolMessage({ tool_call_id: "c1", content: '{"hits": 2}' }),
    ]);
    expect(tc).toMatchObject({
      id: "c1",
      name: "search",
      messageId: "a1",
      status: "finished",
      output: { hits: 2 },
    });
  });

  it("is running while no result exists", () => {
    const [tc] = pairToolCalls([ai("a1", [{ id: "c1", name: "search" }])]);
    expect(tc.status).toBe("running");
    expect(tc.output).toBeUndefined();
  });

  it("takes status and the MCP artifact from the live handle", () => {
    const messages = [
      ai("a1", [{ id: "c1", name: "search" }]),
      // A live tool-role message carries neither status nor artifact.
      new ToolMessage({ tool_call_id: "c1", content: "boom" }),
    ];
    const [errored] = pairToolCalls(messages, [
      handle({ status: "error", error: "boom" }),
    ]);
    expect(errored.status).toBe("error");
    expect(errored.error).toBe("boom");

    const [withArtifact] = pairToolCalls(
      [ai("a1", [{ id: "c1", name: "search" }])],
      [
        handle({
          status: "finished",
          output: {
            content: "ok",
            artifact: { mcp_app_resource_uri: "ui://x", mcp_server_id: "s1" },
          },
        }),
      ],
    );
    expect(withArtifact.output).toBe("ok");
    expect(getMcpAppInfo(withArtifact)).toEqual({
      resourceUri: "ui://x",
      serverId: "s1",
    });
  });

  it("reads status and artifact off a hydrated ToolMessage", () => {
    const [tc] = pairToolCalls([
      ai("a1", [{ id: "c1", name: "search" }]),
      new ToolMessage({
        tool_call_id: "c1",
        content: "User rejected the tool call for search",
        status: "error",
      }),
    ]);
    expect(getToolStepState(tc)).toBe("rejected");
  });
});

describe("getToolStepState", () => {
  it("marks only the hanging tool calls as awaiting approval", () => {
    const [gated, free] = pairToolCalls([
      ai("a1", [
        { id: "c1", name: "send_email" },
        { id: "c2", name: "search" },
      ]),
    ]);
    const names = extractHitlToolNames({
      action_requests: [{ name: "send_email", args: {} }],
    });
    expect(getToolStepState(gated, true, names)).toBe("awaiting-approval");
    expect(getToolStepState(free, true, names)).toBe("running");
    expect(getToolStepState(free, true, null)).toBe("awaiting-approval");
  });
});

describe("groupChains", () => {
  it("chains consecutive tool-only turns under the first AI message", () => {
    const messages = [
      new HumanMessage({ id: "h1", content: "go" }),
      ai("a1", [{ id: "c1", name: "search" }]),
      new ToolMessage({ tool_call_id: "c1", content: "r1" }),
      ai("a2", [{ id: "c2", name: "search" }]),
      new ToolMessage({ tool_call_id: "c2", content: "r2" }),
      ai("a3", [{ id: "c3", name: "search" }], "done"),
      new HumanMessage({ id: "h2", content: "again" }),
      ai("a4", [{ id: "c4", name: "search" }]),
    ];
    const chains = groupChains(messages, pairToolCalls(messages));
    expect([...chains.keys()]).toEqual(["a1", "a4"]);
    expect(chains.get("a1")?.map((s) => s.id)).toEqual(["c1", "c2", "c3"]);
    expect(chains.get("a4")?.map((s) => s.id)).toEqual(["c4"]);
  });

  it("puts a message's reasoning on the rail ahead of its tool calls", () => {
    const thinker = new AIMessage({
      id: "a1",
      content: [
        { type: "reasoning", reasoning: "plan" },
        { type: "text", text: "" },
      ],
      response_metadata: { output_version: "v1" },
      tool_calls: [{ id: "c1", name: "search", args: {}, type: "tool_call" }],
    });
    const answer = new AIMessage({
      id: "a2",
      content: [
        { type: "reasoning", reasoning: "wrap up" },
        { type: "text", text: "done" },
      ],
      response_metadata: { output_version: "v1" },
    });
    const messages = [thinker, new ToolMessage({ tool_call_id: "c1", content: "r" }), answer];
    const chains = groupChains(messages, pairToolCalls(messages));
    expect(chains.get("a1")?.map((s) => s.kind)).toEqual(["reasoning", "tool", "reasoning"]);
    expect(chains.has("a2")).toBe(false);
  });
});

describe("getReasoning", () => {
  it("reads v1 reasoning blocks and the legacy DeepSeek field", () => {
    const v1 = new AIMessage({
      content: [
        { type: "reasoning", reasoning: "think" },
        { type: "text", text: "answer" },
      ],
      response_metadata: { output_version: "v1" },
    });
    expect(getReasoning(v1)).toBe("think");
    expect(v1.text).toBe("answer");

    const legacy = new AIMessage({
      content: "answer",
      additional_kwargs: { reasoning_content: "old think" },
    });
    expect(getReasoning(legacy)).toBe("old think");
    expect(getReasoning(new AIMessage("plain"))).toBeNull();
  });
});

describe("subagent interrupts", () => {
  const rootInterrupt = { id: "r".repeat(32), value: { action_requests: [] }, namespace: [] };
  const nested = {
    id: "n".repeat(32),
    value: { action_requests: [{ name: "send_email", args: { to: "a@b.c" } }] },
    namespace: ["tools:task-1"],
  };

  it("splits the root interrupt from the subagents'", () => {
    expect(splitInterrupts([nested, rootInterrupt])).toEqual({
      root: rootInterrupt,
      nested: [nested],
    });
    expect(splitInterrupts([{ id: "x", value: {} }]).root?.id).toBe("x");
    expect(splitInterrupts([]).root).toBeNull();
  });

  it("claims a subagent's interrupt by execution namespace or discovery key", () => {
    // Live: the SDK bound the execution namespace onto the snapshot.
    expect(findSubagentInterrupt([nested], { id: "call_1", namespace: ["tools:task-1"] })).toBe(
      nested,
    );
    // Hydrated: the snapshot sits on `tools:<tool_call_id>` and the backend
    // addresses the interrupt with the same key.
    const hydrated = { ...nested, namespace: ["tools:call_1"] };
    expect(findSubagentInterrupt([hydrated], { id: "call_1", namespace: ["tools:call_1"] })).toBe(
      hydrated,
    );
    expect(findSubagentInterrupt([nested], { id: "call_9", namespace: ["tools:other"] })).toBeNull();
  });

  it("never matches by content: identical siblings do not share an interrupt", () => {
    const sibling = { id: "call_2", namespace: ["tools:call_2"] };
    expect(findSubagentInterrupt([nested], sibling)).toBeNull();
  });
});
