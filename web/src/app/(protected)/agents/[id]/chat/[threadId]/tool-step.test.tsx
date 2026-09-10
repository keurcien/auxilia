import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ToolCallView } from "./message-helpers";
import { ToolStep } from "./tool-step";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "agent-1", threadId: "thread-1" }),
}));

const fetchThreadMessage = vi.fn();
vi.mock("@/lib/api/thread-messages", () => ({
  fetchThreadMessage: (...args: unknown[]) => fetchThreadMessage(...args),
}));

const describeTool = () => ({
  serverName: "Code execution",
  toolName: "grep",
  icon: undefined,
});

function view(overrides: Partial<ToolCallView>): ToolCallView {
  return {
    id: "call_1",
    callId: "call_1",
    name: "grep",
    args: { pattern: "statRow" },
    messageId: "ai_1",
    status: "finished",
    output: "line 1\nline 2",
    error: undefined,
    artifact: undefined,
    ...overrides,
  };
}

/** Steps are collapsed by default; their content mounts on expand. */
function expand() {
  fireEvent.click(screen.getByText("Grep"));
}

beforeEach(() => {
  fetchThreadMessage.mockReset();
});

describe("ToolStep result loading", () => {
  it("renders a whole result with no load affordance and no fetch", () => {
    render(<ToolStep tc={view({})} state="done" describe={describeTool} />);
    expand();
    expect(screen.getByText(/line 1/)).toBeInTheDocument();
    expect(screen.queryByText("Load full output")).toBeNull();
    expect(fetchThreadMessage).not.toHaveBeenCalled();
  });

  it("does not fetch a truncated result until the step is expanded", () => {
    fetchThreadMessage.mockResolvedValue({
      id: "tool_1",
      type: "tool",
      content: "whole",
    });
    render(
      <ToolStep
        tc={view({
          output: "part",
          resultMessageId: "tool_1",
          truncatedChars: 34_000,
        })}
        state="done"
        describe={describeTool}
      />,
    );
    expect(fetchThreadMessage).not.toHaveBeenCalled();
  });

  it("fetches the whole result on expand and swaps it in", async () => {
    fetchThreadMessage.mockResolvedValue({
      id: "tool_1",
      type: "tool",
      content: "the whole output, every line of it",
    });
    render(
      <ToolStep
        tc={view({
          output: "the whole out",
          resultMessageId: "tool_1",
          truncatedChars: 34_000,
        })}
        state="done"
        describe={describeTool}
      />,
    );
    expand();
    expect(
      screen.getByText(/Loading the full output \(34 K chars\)/),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(
        screen.getByText("the whole output, every line of it"),
      ).toBeInTheDocument();
    });
    expect(fetchThreadMessage).toHaveBeenCalledWith("thread-1", "tool_1");
    expect(screen.queryByText(/Showing the first/)).toBeNull();
  });

  it("keeps the preview, shows the error and offers a retry when the load fails", async () => {
    fetchThreadMessage
      .mockRejectedValueOnce(new Error("Could not load the tool output (502)."))
      .mockResolvedValueOnce({
        id: "tool_2",
        type: "tool",
        content: "recovered",
      });
    render(
      <ToolStep
        tc={view({
          output: "partial",
          resultMessageId: "tool_2",
          truncatedChars: 20_000,
        })}
        state="done"
        describe={describeTool}
      />,
    );
    expand();
    await waitFor(() => {
      expect(
        screen.getByText("Could not load the tool output (502)."),
      ).toBeInTheDocument();
    });
    expect(screen.getByText("partial")).toBeInTheDocument();
    expect(
      screen.getByText(/Showing the first 7 chars of 20 K chars/),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByText("Retry"));
    await waitFor(() => {
      expect(screen.getByText("recovered")).toBeInTheDocument();
    });
    expect(fetchThreadMessage).toHaveBeenCalledTimes(2);
  });
});
