/**
 * One message of a thread, whole (`GET /threads/{id}/messages/{id}`).
 *
 * Thread snapshots (`/state`, `/history`) ship tool results cut at the
 * backend's preview limit; this fetches the rest when a step asks for it.
 * Raw `fetch`, not the axios client: the body is protocol-shaped (snake_case,
 * arbitrary tool payloads) and must not be camelized.
 */
export type ThreadMessage = {
  id: string | null;
  type: string;
  content: unknown;
  artifact?: unknown;
};

export async function fetchThreadMessage(
  threadId: string,
  messageId: string,
): Promise<ThreadMessage> {
  const url = `/api/backend/threads/${encodeURIComponent(threadId)}/messages/${encodeURIComponent(messageId)}`;
  const response = await fetch(url, { credentials: "include" });
  if (!response.ok) {
    throw new Error(`Could not load the tool output (${response.status}).`);
  }
  return (await response.json()) as ThreadMessage;
}
