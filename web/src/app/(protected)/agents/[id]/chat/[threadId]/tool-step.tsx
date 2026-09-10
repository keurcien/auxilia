"use client";

import { memo, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { BanIcon, Loader2, XCircleIcon } from "lucide-react";
import { parseToolPayload } from "@langchain/langgraph-sdk/stream";
import {
  ChainStep,
  ChainStepIcon,
  NeedsApprovalBadge,
  StepCode,
  StepSection,
  TERMINAL_ICON,
  humanizeToolName,
  isSandboxTool,
  summarizeToolArgs,
} from "@/components/ai-elements/chain-of-thought";
import { cn } from "@/lib/utils";
import { fetchThreadMessage } from "@/lib/api/thread-messages";
import type { HitlDecision } from "@/hooks/use-hitl-approvals";
import {
  type ToolCallView,
  type ToolStepState,
  getToolMetadata,
} from "./message-helpers";

type ToolIdentity = {
  serverName: string;
  toolName: string;
  icon: string | undefined;
};

export type DescribeTool = (toolName: string) => ToolIdentity;

/** Resolve `<server>_<tool>` names against the workspace's MCP servers. */
export function useDescribeTool(
  mcpServers: readonly { name: string; iconUrl?: string | null }[],
): DescribeTool {
  return useMemo(() => {
    const known = mcpServers
      .map((s) => s.name)
      .sort((a, b) => b.length - a.length);
    return (name: string) => {
      if (isSandboxTool(name)) {
        return { serverName: "Code execution", toolName: name, icon: TERMINAL_ICON };
      }
      const { serverName, toolName } = getToolMetadata(name, known);
      return {
        serverName,
        toolName,
        icon: mcpServers.find((s) => s.name === serverName)?.iconUrl ?? undefined,
      };
    };
  }, [mcpServers]);
}

type ToolStepApproval = {
  decided: HitlDecision | undefined;
  disabled: boolean;
  onDecide: (decision: HitlDecision) => void;
};

export type ToolStepProps = {
  tc: ToolCallView;
  state: ToolStepState;
  describe: DescribeTool;
  /** Smaller type, for a subagent's nested rail. */
  nested?: boolean;
  /** Approve / deny footer — root chains only. */
  approval?: ToolStepApproval;
};

/** One tool call on the chain rail, at the root or nested in a subagent. */
export const ToolStep = memo(function ToolStep({
  tc,
  state,
  describe,
  nested = false,
  approval,
}: ToolStepProps) {
  const { serverName, toolName, icon } = describe(tc.name);
  const awaiting = state === "awaiting-approval";
  const showResult =
    state === "rejected" || state === "error" || tc.output !== undefined;
  const showApproval = awaiting && approval != null;
  const hasDetails = tc.args !== undefined || showResult || showApproval;

  const meta =
    state === "awaiting-approval" ? (
      <NeedsApprovalBadge />
    ) : state === "running" ? (
      <Loader2 className="size-3 animate-spin text-petrol" />
    ) : state === "error" ? (
      <XCircleIcon className="size-3.5 text-destructive" />
    ) : state === "rejected" ? (
      <BanIcon className="size-3.5 text-meta dark:text-panel-dim" />
    ) : undefined;

  return (
    <ChainStep
      nested={nested}
      node={<ChainStepIcon icon={icon} name={serverName} />}
      title={humanizeToolName(toolName)}
      summary={summarizeToolArgs(tc.args)}
      meta={meta}
      lockOpen={awaiting && approval?.decided == null}
    >
      {hasDetails && (
        <>
          {tc.args !== undefined && (
            <StepSection label="PARAMETERS">
              <StepCode value={tc.args} />
            </StepSection>
          )}
          {state === "rejected" ? (
            <StepSection label="DENIED">
              <StepCode value="Denied by the user — the tool was not executed." />
            </StepSection>
          ) : state === "error" ? (
            <StepSection label="ERROR" error>
              <StepCode value={tc.error} />
            </StepSection>
          ) : (
            tc.output !== undefined && (
              <StepSection label="RESULT">
                <ToolResult key={tc.resultMessageId ?? tc.id} tc={tc} />
              </StepSection>
            )
          )}
          {showApproval && (
        <div className="flex items-center gap-2 pt-1">
          <ApprovalButton
            approval={approval}
            decision="approve"
            className="bg-petrol text-white transition-opacity hover:opacity-90"
          >
            Approve
          </ApprovalButton>
          <ApprovalButton
            approval={approval}
            decision="reject"
            className="border border-input bg-card text-foreground transition-colors hover:border-border-hover"
          >
            Deny
          </ApprovalButton>
        </div>
          )}
        </>
      )}
    </ChainStep>
  );
});

/**
 * A step's result. The thread snapshot carries at most a preview of a large
 * result (`tc.truncatedChars`); the rest is fetched when the step is expanded
 * — `ChainStep` mounts its content only while open, so mounting *is* the
 * expand — and a page load never parses or lays out megabytes of tool output
 * nobody looked at.
 */
const ToolResult = ({ tc }: { tc: ToolCallView }) => {
  // Keyed by the result message in `ToolStep`, so a different result mounts a
  // fresh instance: no load state leaks from one message to the next.
  const params = useParams<{ threadId?: string }>();
  const threadId = params.threadId;
  const [full, setFull] = useState<{ forMessage: string; output: unknown } | null>(
    null,
  );
  const [loadError, setLoadError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  const loaded =
    full != null && full.forMessage === tc.resultMessageId ? full.output : undefined;
  const truncated = loaded === undefined && tc.truncatedChars != null;
  // A result without a persisted message id (or outside a thread route) can
  // only show its preview; the note still says so.
  const canLoad = truncated && tc.resultMessageId != null && threadId != null;
  // Loading is implied: a loadable result with no error yet is being fetched.
  const loading = canLoad && loadError == null;

  useEffect(() => {
    if (!canLoad || loadError != null) return;
    const messageId = tc.resultMessageId as string;
    let cancelled = false;
    fetchThreadMessage(threadId as string, messageId)
      .then((message) => {
        if (cancelled) return;
        const content = message.content;
        setFull({
          forMessage: messageId,
          output: typeof content === "string" ? parseToolPayload(content) : content,
        });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setLoadError(
          err instanceof Error ? err.message : "Could not load the tool output.",
        );
      });
    return () => {
      cancelled = true;
    };
  }, [canLoad, threadId, tc.resultMessageId, loadError, attempt]);

  return (
    <>
      <StepCode value={loaded ?? tc.output} />
      {truncated && (
        <div className="flex items-center gap-2 pt-1 text-[11.5px] text-meta dark:text-panel-dim">
          {loading ? (
            <>
              <Loader2 className="size-3 animate-spin" />
              <span>
                Loading the full output ({formatChars(tc.truncatedChars ?? 0)})…
              </span>
            </>
          ) : (
            <>
              <span>
                Showing the first {formatChars(String(tc.output ?? "").length)} of{" "}
                {formatChars(tc.truncatedChars ?? 0)}.
              </span>
              {loadError && <span className="text-destructive">{loadError}</span>}
              {canLoad && (
                <button
                  type="button"
                  onClick={() => {
                    setLoadError(null);
                    setAttempt((n) => n + 1);
                  }}
                  className="cursor-pointer font-semibold text-petrol underline-offset-2 hover:underline"
                >
                  Retry
                </button>
              )}
            </>
          )}
        </div>
      )}
    </>
  );
};

const formatChars = (n: number): string =>
  n >= 1_000_000
    ? `${(n / 1_000_000).toFixed(1)} M chars`
    : n >= 1_000
      ? `${Math.round(n / 1_000)} K chars`
      : `${n} chars`;

const ApprovalButton = ({
  approval,
  decision,
  className,
  children,
}: {
  approval: ToolStepApproval;
  decision: HitlDecision;
  className: string;
  children: string;
}) => (
  <button
    type="button"
    disabled={approval.decided != null || approval.disabled}
    onClick={() => {
      approval.onDecide(decision);
    }}
    className={cn(
      "cursor-pointer rounded-[7px] px-4 py-1.5 text-[12.5px] font-semibold disabled:cursor-not-allowed",
      className,
      approval.decided != null && approval.decided !== decision && "opacity-40",
    )}
  >
    {children}
  </button>
);
