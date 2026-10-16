import { api } from "@/lib/api/client";

export interface SandboxMcpRequest {
  id: string;
  scope: string;
  phase: string;
  agent: string;
  tool: string;
  arguments: Record<string, unknown>;
  status: "approval_required" | "oauth_required";
  authUrl?: string;
}

export async function pendingSandboxMcp(threadId: string, signal?: AbortSignal): Promise<SandboxMcpRequest[]> {
  return (await api.get<SandboxMcpRequest[]>(`/threads/${threadId}/sandbox-mcp/pending`, { signal })).data;
}

export async function decideSandboxMcp(threadId: string, request: SandboxMcpRequest, type: "approve" | "reject"): Promise<void> {
  await api.post(`/threads/${threadId}/sandbox-mcp/${request.scope}/${request.id}/decision`, { type, phase: request.phase });
}
