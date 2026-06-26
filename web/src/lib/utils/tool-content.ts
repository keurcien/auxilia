// Helpers for reading LangChain `ToolMessage` content in the chat UI.
//
// A ToolMessage `content` is either a plain string or a list of content blocks
// (e.g. `[{ type: "text", text: "…" }]`). MCP tool *errors* (status="error")
// surface via langchain-mcp-adapters as a content-block list, so reading the
// error text means flattening those blocks — not just checking `typeof === "string"`.

/**
 * Flatten a ToolMessage `content` (string or content-block list) to plain text.
 * Returns `undefined` when there is no usable text to show.
 */
export function extractToolMessageText(content: unknown): string | undefined {
	if (typeof content === "string") {
		return content.length > 0 ? content : undefined;
	}
	if (Array.isArray(content)) {
		const text = content
			.filter(
				(c): c is { type?: string; text?: string } =>
					!!c && typeof c === "object",
			)
			.map((c) => (typeof c.text === "string" ? c.text : ""))
			.join("");
		return text.length > 0 ? text : undefined;
	}
	return undefined;
}

/**
 * Resolve the error text to display for a failed tool call. Falls back to a
 * generic message only when the content has no readable text at all.
 */
export function extractToolErrorText(content: unknown): string {
	return extractToolMessageText(content) ?? "Tool execution failed";
}
