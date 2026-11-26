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

export type RefusalInfo = {
  /** The provider's human-readable reason (e.g. Anthropic's cyber safeguard). */
  explanation: string;
  /** The refusal category when the provider tags one (e.g. `cyber`). */
  category: string | null;
};

/** A model refusal: the run completes with an empty answer, the reason sitting
 *  in `response_metadata.stop_details`. Surfaced so an empty assistant turn
 *  reads as a refusal instead of silence. */
export function getRefusal(message: BaseMessage): RefusalInfo | null {
  const metadata = message.response_metadata as
    | {
        stop_details?: {
          type?: unknown;
          explanation?: unknown;
          category?: unknown;
        };
        stop_reason?: unknown;
        normalized_finish_reason?: unknown;
      }
    | undefined;
  if (metadata == null) return null;
  const details = metadata.stop_details;
  const isRefusal =
    details?.type === "refusal" ||
    metadata.stop_reason === "refusal" ||
    metadata.normalized_finish_reason === "refusal";
  if (!isRefusal) return null;
  const explanation =
    typeof details?.explanation === "string" && details.explanation.trim()
      ? details.explanation.trim()
      : "The model declined to respond to this request.";
  const category =
    typeof details?.category === "string" && details.category.trim()
      ? details.category.trim()
      : null;
  return { explanation, category };
}

/** Attachments of a human turn — the `image_url` / `file` blocks the composer
 *  submits (see `handleSubmit` on the chat page). */
export function getFileAttachments(message: BaseMessage): AttachmentData[] {
  if (!Array.isArray(message.content)) return [];
  const attachments: AttachmentData[] = [];
  const inlineTextFiles = message.additional_kwargs?.inline_text_files;
  const inlineByIndex = new Map<number, Record<string, unknown>>();
  if (Array.isArray(inlineTextFiles)) {
    for (const item of inlineTextFiles) {
      if (
        item != null &&
        typeof item === "object" &&
        typeof (item as { block_index?: unknown }).block_index === "number"
      ) {
        inlineByIndex.set(
          (item as { block_index: number }).block_index,
          item as Record<string, unknown>,
        );
      }
    }
  }
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
    } else if (b.type === "text" && inlineByIndex.has(idx)) {
      const inlineFile = inlineByIndex.get(idx)!;
      const filename =
        typeof inlineFile.filename === "string"
          ? inlineFile.filename
          : "file.txt";
      const mediaType =
        typeof inlineFile.media_type === "string"
          ? inlineFile.media_type
          : "text/plain";
      const blockText = typeof b.text === "string" ? b.text : "";
      const prefix = `Attached text file "${filename}":\n\n`;
      const content = blockText.startsWith(prefix)
        ? blockText.slice(prefix.length)
        : blockText;
      attachments.push({
        id: `${message.id}-file-${idx}`,
        type: "file",
        url: `data:${mediaType};charset=utf-8,${encodeURIComponent(content)}`,
        filename,
        mediaType,
      });
    }
  });
  return attachments;
}

/** Persistent thread-file ids recorded on a human message. */
export function getAttachmentIds(message: BaseMessage): string[] {
  const attachments = message.additional_kwargs?.attachments;
  if (!Array.isArray(attachments)) return [];
  return attachments.flatMap((item) => {
    if (typeof item === "string") return [item];
    if (
      typeof item === "object" &&
      item !== null &&
      typeof (item as { id?: unknown }).id === "string"
    ) {
      return [(item as { id: string }).id];
    }
    return [];
  });
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
