"use client";

import { memo, useMemo } from "react";
import { BanIcon, Loader2, XCircleIcon } from "lucide-react";
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
                <StepCode value={tc.output} />
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
