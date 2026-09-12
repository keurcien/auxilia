import type { BaseMessage } from "@langchain/core/messages";
import type { AttachmentData } from "@/components/ai-elements/attachments";

/** Reasoning text: v1 `reasoning` blocks, or DeepSeek's `reasoning_content`
 *  on checkpoints written before the v3 protocol. */
export function getReasoning(message: BaseMessage): string | null {
  const blocks = message.contentBlocks
    .filter((b) => b.type === "reasoning")
    .map((b) => (b as { reasoning?: string }).reasoning ?? "");
  if (blocks.length > 0) return blocks.join("\n");
  const legacy = message.additional_kwargs?.reasoning_content;
  return typeof legacy === "string" && legacy ? legacy : null;
}

/** Attachments of a human turn — the `image_url` / `file` blocks the composer
 *  submits (see `handleSubmit` on the chat page). */
export function getFileAttachments(message: BaseMessage): AttachmentData[] {
  if (!Array.isArray(message.content)) return [];
  const attachments: AttachmentData[] = [];
  message.content.forEach((block, idx) => {
    const b = block as Record<string, unknown>;
    if (b.type === "image_url") {
      const image = b.image_url;
      const url =
        typeof image === "string"
          ? image
          : ((image as { url?: string } | undefined)?.url ?? "");
      const mediaType = url.match(/^data:([^;,]+)/)?.[1] ?? "image/jpeg";
      // `image/svg+xml` → svg, `image/x-icon` → icon, `image/jpeg` → jpg.
      const extension =
        mediaType.split("/")[1]?.split("+")[0].replace(/^x-/, "").replace("jpeg", "jpg") ??
        "jpg";
      attachments.push({
        id: `${message.id}-file-${idx}`,
        type: "file",
        url:
          url.startsWith("data:") || /^https?:\/\//.test(url)
            ? url
            : `data:image/jpeg;base64,${url}`,
        filename: `Image.${extension}`,
        mediaType,
      });
    } else if (b.type === "file") {
      const mediaType =
        (b.mime_type as string | undefined) ?? "application/octet-stream";
      attachments.push({
        id: `${message.id}-file-${idx}`,
        type: "file",
        url: `data:${mediaType};base64,${(b.base64 as string | undefined) ?? ""}`,
        filename: (b.filename as string | undefined) ?? "file",
        mediaType,
      });
    }
  });
  return attachments;
}

// ---------------------------------------------------------------------------
// Tool identity
// ---------------------------------------------------------------------------

/** How MCP tool names are namespaced on the backend: `<server>_<tool>`. */
export const sanitizeToolIdentifier = (value: string): string => {
  const sanitized = value
    .replace(/[^a-zA-Z0-9_-]/g, "_")
    .replace(/^_+|_+$/g, "");
  return sanitized || "tool";
};

/** Split `<server>_<tool>` back apart. `knownServerNames` must be sorted
 *  longest-first so `google_sheets_read` is not claimed by `google`. */
export const getToolMetadata = (
  toolName: string,
  knownServerNames: readonly string[],
) => {
  for (const serverName of knownServerNames) {
    for (const alias of [serverName, sanitizeToolIdentifier(serverName)]) {
      if (toolName === alias || toolName.startsWith(`${alias}_`)) {
        const suffix = toolName.slice(alias.length);
        const name = suffix.startsWith("_") ? suffix.slice(1) : suffix;
        return { serverName, toolName: name || toolName };
      }
    }
  }
  const separatorIndex = toolName.indexOf("_");
  if (separatorIndex === -1) return { serverName: toolName, toolName };
  return {
    serverName: toolName.slice(0, separatorIndex),
    toolName: toolName.slice(separatorIndex + 1),
  };
};

// ---------------------------------------------------------------------------
// Tool calls
// ---------------------------------------------------------------------------
