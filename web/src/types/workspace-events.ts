export const WORKSPACE_EVENT_KINDS = [
  "agents",
  "triggers",
  "mcp_servers",
  "skills",
  "threads",
  "projects",
  "runs",
  "prompt_queue",
  "trigger_history",
] as const;

export type WorkspaceEventKind = (typeof WORKSPACE_EVENT_KINDS)[number];

export type WorkspaceInvalidation = {
  kind: WorkspaceEventKind;
  threadId?: string;
};

export function isWorkspaceInvalidation(
  value: unknown,
): value is WorkspaceInvalidation {
  if (value === null || typeof value !== "object") return false;
  const event = value as Record<string, unknown>;
  return (
    typeof event.kind === "string" &&
    WORKSPACE_EVENT_KINDS.includes(event.kind as WorkspaceEventKind) &&
    (event.threadId === undefined || typeof event.threadId === "string")
  );
}
