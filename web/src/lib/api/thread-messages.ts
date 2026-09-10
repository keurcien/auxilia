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
  const path = `/api/backend/threads/${encodeURIComponent(threadId)}/messages/${encodeURIComponent(messageId)}`;
  // Origin-pinned by construction: a fixed same-origin path whose two
  // segments are URL-encoded ids, so it cannot reach another host. The taint
  // scanner cannot see that sanitizer.
  // nosemgrep
  const response = await fetch(new URL(path, window.location.origin), {
    credentials: "include",
  });
  if (!response.ok) {
    throw new Error(`Could not load the tool output (${response.status}).`);
  }
  return (await response.json()) as ThreadMessage;
}
