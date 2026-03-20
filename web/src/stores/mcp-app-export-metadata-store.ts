import { create } from "zustand";
import type { NormalizedExportMetadata } from "@/lib/mcp-app-update-model-context";

export type McpAppExportMetadataRecord = NormalizedExportMetadata & {
	threadId: string;
	messageId: string;
	toolCallId: string;
	receivedAt: string;
};

type SetExportMetadataParams = {
	threadId: string;
	messageId: string;
	toolCallId: string;
	metadata: NormalizedExportMetadata;
};

interface McpAppExportMetadataState {
	metadataByKey: Map<string, McpAppExportMetadataRecord>;
	setExportMetadata: (params: SetExportMetadataParams) => void;
	clearThreadExportMetadata: (threadId: string) => void;
}

export const buildExportMetadataKey = (
	threadId: string,
	messageId: string,
	toolCallId: string,
): string => `${threadId}::${messageId}::${toolCallId}`;

export const useMcpAppExportMetadataStore =
	create<McpAppExportMetadataState>((set) => ({
		metadataByKey: new Map(),
		setExportMetadata: ({ threadId, messageId, toolCallId, metadata }) =>
			set((state) => {
				const next = new Map(state.metadataByKey);
				next.set(buildExportMetadataKey(threadId, messageId, toolCallId), {
					...metadata,
					threadId,
					messageId,
					toolCallId,
					receivedAt: new Date().toISOString(),
				});
				return { metadataByKey: next };
			}),
		clearThreadExportMetadata: (threadId) =>
			set((state) => {
				const next = new Map(state.metadataByKey);
				for (const [key, record] of next.entries()) {
					if (record.threadId === threadId) {
						next.delete(key);
					}
				}
				return { metadataByKey: next };
			}),
	}));

export const useMcpAppExportMetadata = (
	threadId: string,
	messageId: string,
	toolCallId: string,
): McpAppExportMetadataRecord | null =>
	useMcpAppExportMetadataStore((state) => {
		const key = buildExportMetadataKey(threadId, messageId, toolCallId);
		return state.metadataByKey.get(key) ?? null;
	});
