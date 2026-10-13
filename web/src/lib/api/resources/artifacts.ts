import { API_BASE_URL } from "@/lib/api/client";
import { protocolFetch } from "@/lib/api/protocol";

export interface Artifact {
  id: string;
  thread_id: string;
  tool_call_id: string;
  title: string;
  filename: string;
  mime_type: string;
  size: number;
  temporary: boolean;
  created_at: string | null;
}

export function contentUrl(artifact: Artifact): string {
  return `${API_BASE_URL}/threads/${encodeURIComponent(artifact.thread_id)}/artifacts/${encodeURIComponent(artifact.id)}/content`;
}

/** Browser navigation (new tab): the backend runs the Google consent, then
 *  redirects to the Slides copy of this PPTX. */
export function slidesExportUrl(artifact: Artifact): string {
  return `${contentUrl(artifact).slice(0, -"/content".length)}/export/slides`;
}

export async function listArtifacts(
  threadId: string,
  signal: AbortSignal,
): Promise<Artifact[]> {
  const items: Artifact[] = [];
  for (;;) {
    // Keyset paging: files published mid-listing never shift a page boundary.
    const last = items.at(-1);
    const query = last ? `?after=${encodeURIComponent(last.id)}` : "";
    const response = await protocolFetch(
      `${API_BASE_URL}/threads/${encodeURIComponent(threadId)}/artifacts${query}`,
      { signal },
    );
    if (!response.ok) throw new Error("Could not load conversation files.");
    const page = (await response.json()) as Artifact[];
    items.push(...page);
    if (page.length < 100) return items;
  }
}

let htmlSources: Promise<string[]> | undefined;

/** Where HTML artifacts may load scripts, styles, fonts and images from
 *  (`ARTIFACT_HTML_SOURCES`). Asked once per page load; a failure means inline
 *  content only, and is retried on the next preview. */
export function getHtmlSources(): Promise<string[]> {
  htmlSources ??= protocolFetch(`${API_BASE_URL}/artifacts/viewer`)
    .then(async (response) => {
      if (!response.ok) throw new Error("viewer settings unavailable");
      return ((await response.json()) as { html_sources: string[] })
        .html_sources;
    })
    .catch(() => {
      htmlSources = undefined;
      return [];
    });
  return htmlSources;
}

export async function readArtifact(
  artifact: Artifact,
  signal: AbortSignal,
): Promise<ArrayBuffer> {
  const response = await protocolFetch(contentUrl(artifact), { signal });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      error?: string;
      detail?: string;
    } | null;
    if (body?.error === "artifact_gone")
      throw new Error(body.detail ?? "This file is no longer available.");
    throw new Error("This file is unavailable right now. Retry in a moment.");
  }
  return response.arrayBuffer();
}
