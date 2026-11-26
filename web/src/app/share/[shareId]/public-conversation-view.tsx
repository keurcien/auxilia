"use client";

import {
	coerceMessageLikeToMessage,
	isAIMessage,
	isHumanMessage,
	isToolMessage,
	type BaseMessage,
	type BaseMessageLike,
} from "@langchain/core/messages";
import {
	Brain,
	Clock3,
	Cpu,
	Download,
	FileText,
	Globe2,
	ImageIcon,
	LockKeyhole,
	MessageSquare,
} from "lucide-react";
import Image from "next/image";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ImageGallery } from "@/components/artifacts/image-gallery";
import {
	Conversation,
	ConversationContent,
} from "@/components/ai-elements/conversation";
import {
	Message,
	MessageContent,
	MessageResponse,
} from "@/components/ai-elements/message";
import {
	ChainStepIcon,
	isSandboxTool,
} from "@/components/ai-elements/chain-of-thought";
import { CodeBlock } from "@/components/ai-elements/code-block";
import {
	ThreadMap,
	threadMapAnchor,
} from "@/components/ai-elements/thread-map";
import {
	getAttachmentIds,
	getFileAttachments,
	getImageGallery,
	getReasoning,
	getToolMetadata,
	pairToolCalls,
	type ToolCallView,
} from "@/lib/transcript";
import {
	getPublicArtifact,
	getPublicConversation,
	type PublicConversation,
	type PublicConversationArtifact,
	type PublicConversationRun,
} from "@/lib/api/resources/threads";
import {
	HoverCard,
	HoverCardContent,
	HoverCardTrigger,
} from "@/components/ui/hover-card";

function formatBytes(size: number): string {
	if (size < 1024) return `${size} B`;
	if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
	return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function toolLabel(name: string): string {
	return name
		.replaceAll(/[-_]+/g, " ")
		.replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function printable(value: unknown): string {
	if (typeof value === "string") return value;
	try {
		return JSON.stringify(value, null, 2);
	} catch {
		return String(value);
	}
}

function printableLanguage(value: unknown): "json" | "plaintext" {
	if (typeof value !== "string") return "json";
	try {
		JSON.parse(value);
		return "json";
	} catch {
		return "plaintext";
	}
}

function formatDuration(durationMs: number): string {
	const seconds = durationMs / 1000;
	if (seconds < 1) return `${Math.max(0.1, seconds).toFixed(1)} s`;
	if (seconds < 10) return `${seconds.toFixed(1)} s`;
	if (seconds < 60) return `${Math.round(seconds)} s`;
	const minutes = Math.floor(seconds / 60);
	const remainingSeconds = Math.round(seconds % 60);
	if (minutes < 60) return `${minutes} min ${remainingSeconds} s`;
	const hours = Math.floor(minutes / 60);
	return `${hours} h ${minutes % 60} min`;
}

function userTurnKey(message: BaseMessage, index: number): string {
	return message.id != null ? String(message.id) : `user:${index}`;
}

function runDurationMs(run: PublicConversationRun): number | null {
	const startedAt = Date.parse(run.started_at ?? "");
	const updatedAt = Date.parse(run.updated_at);
	if (!Number.isFinite(startedAt) || !Number.isFinite(updatedAt)) return null;
	return Math.max(0, updatedAt - startedAt);
}

type TurnRunMetadata = {
	promptedAt: string;
	durationMs?: number;
};

function mapRunMetadataToUserTurns(
	messages: readonly BaseMessage[],
	runs: readonly PublicConversationRun[],
): Map<string, TurnRunMetadata> {
	const userTurns = messages.flatMap((message, index) =>
		isHumanMessage(message)
			? [{ message, key: userTurnKey(message, index) }]
			: [],
	);
	const byMessageId = new Map(
		userTurns.flatMap(({ message, key }) =>
			message.id != null ? [[String(message.id), key] as const] : [],
		),
	);
	const metadata = new Map<string, TurnRunMetadata>();
	const accumulated = new Map<string, number>();
	const assignedTurns = new Set<string>();
	let fallbackIndex = 0;
	let currentTurn: string | null = null;

	const chronological = [...runs].sort((left, right) => {
		const leftAt = Date.parse(left.started_at ?? left.created_at);
		const rightAt = Date.parse(right.started_at ?? right.created_at);
		return leftAt - rightAt;
	});
	for (const run of chronological) {
		if (run.kind === "prompt") {
			const exact =
				run.input_message_id != null
					? byMessageId.get(run.input_message_id)
					: undefined;
			while (
				exact == null &&
				userTurns[fallbackIndex] != null &&
				assignedTurns.has(userTurns[fallbackIndex].key)
			) {
				fallbackIndex += 1;
			}
			currentTurn = exact ?? userTurns[fallbackIndex]?.key ?? null;
			if (currentTurn != null) {
				assignedTurns.add(currentTurn);
				accumulated.set(currentTurn, 0);
				metadata.set(currentTurn, { promptedAt: run.created_at });
				if (exact == null) fallbackIndex += 1;
			}
		} else if (run.kind === "regenerate" && currentTurn != null) {
			accumulated.set(currentTurn, 0);
		} else if (run.kind !== "resume") {
			continue;
		}
		if (currentTurn == null) continue;
		const duration = runDurationMs(run);
		if (duration != null) {
			accumulated.set(
				currentTurn,
				(accumulated.get(currentTurn) ?? 0) + duration,
			);
		}
		if (run.status === "pending" || run.status === "running") {
			const current = metadata.get(currentTurn);
			if (current) metadata.set(currentTurn, { promptedAt: current.promptedAt });
		} else if (run.status === "interrupted") {
			const current = metadata.get(currentTurn);
			if (current) metadata.set(currentTurn, { promptedAt: current.promptedAt });
		} else {
			const current = metadata.get(currentTurn);
			if (current) {
				metadata.set(currentTurn, {
					...current,
					durationMs: accumulated.get(currentTurn) ?? 0,
				});
			}
		}
	}
	return metadata;
}

function formatPromptTimestamp(value: string): string | null {
	const date = new Date(value);
	if (!Number.isFinite(date.getTime())) return null;
	return new Intl.DateTimeFormat(undefined, {
		weekday: "short",
		day: "numeric",
		month: "short",
		hour: "2-digit",
		minute: "2-digit",
	}).format(date);
}

function formatCost(amount: string): string {
	const value = Number(amount);
	return value > 0 && value < 0.01 ? "<\u20090.01$" : `${value.toFixed(2)}$`;
}

function formatExactCost(amount: string): string {
	return `${Number(amount).toLocaleString("en-US", {
		maximumFractionDigits: 10,
	})}$`;
}

type PublicConversationCost = NonNullable<PublicConversation["cost"]>;

function PublicCostBreakdown({ cost }: { cost: PublicConversationCost }) {
	const pricedCallCount = cost.call_count - cost.unpriced_call_count;
	const usage = cost.usage_details;
	const amounts = cost.cost_details;
	if (usage && amounts) {
		const rows = [
			["Input", usage.input, amounts.input],
			["Cached input", usage.input_cache_read, amounts.input_cache_read],
			[
				"Cache write",
				usage.input_cache_creation,
				amounts.input_cache_creation,
			],
			["Output", usage.output, amounts.output],
		] as const;
		return (
			<div className="text-[12px]">
				<table className="w-full tabular-nums">
					<thead>
						<tr className="text-meta">
							<th className="pb-1 text-left font-medium" />
							<th className="pb-1 text-right font-medium">Tokens</th>
							<th className="pb-1 pl-4 text-right font-medium">Cost</th>
						</tr>
					</thead>
					<tbody>
						{rows.map(([label, tokens, amount]) => (
							<tr key={label}>
								<td className="py-0.5 text-subtle">{label}</td>
								<td className="py-0.5 text-right">
									{tokens.toLocaleString("en-US")}
								</td>
								<td className="py-0.5 pl-4 text-right font-mono">
									{formatExactCost(amount)}
								</td>
							</tr>
						))}
						<tr className="border-t border-border font-semibold">
							<td className="pt-1.5">Total</td>
							<td className="pt-1.5 text-right">
								{usage.total.toLocaleString("en-US")}
							</td>
							<td className="pt-1.5 pl-4 text-right font-mono">
								{formatExactCost(amounts.total)}
							</td>
						</tr>
					</tbody>
				</table>
				{!cost.complete && (
					<p className="mt-2 text-meta">
						{cost.unpriced_call_count} of {cost.call_count} model calls have
						no price or usage. This subtotal covers priced calls only.
					</p>
				)}
			</div>
		);
	}
	return (
		<div className="text-[12px]">
			<p className="font-semibold text-foreground">
				{pricedCallCount === 0 ? "Cost unavailable" : "Cost details"}
			</p>
			<dl className="mt-2 space-y-1.5 tabular-nums">
				<div className="flex items-center justify-between gap-6">
					<dt className="text-subtle">Model calls</dt>
					<dd>{cost.call_count.toLocaleString("en-US")}</dd>
				</div>
				<div className="flex items-center justify-between gap-6">
					<dt className="text-subtle">Tokens</dt>
					<dd>{cost.total_tokens.toLocaleString("en-US")}</dd>
				</div>
				{pricedCallCount > 0 && (
					<div className="flex items-center justify-between gap-6 border-t border-border pt-1.5 font-semibold">
						<dt>{cost.complete ? "Total" : "Known subtotal"}</dt>
						<dd className="font-mono">{formatExactCost(cost.known_cost)}</dd>
					</div>
				)}
			</dl>
			{!cost.complete && (
				<p className="mt-2 leading-5 text-meta">
					{cost.unpriced_call_count} of {cost.call_count} model calls have no
					retained price or usage.
				</p>
			)}
		</div>
	);
}

function ActivityBreakdown({
	humanCount,
	assistantCount,
	toolCalls,
}: {
	humanCount: number;
	assistantCount: number;
	toolCalls: ToolCallView[];
}) {
	const finishedCount = toolCalls.filter(
		(call) => call.status === "finished",
	).length;
	const failedCount = toolCalls.filter((call) => call.status === "error").length;
	const incompleteCount = toolCalls.length - finishedCount - failedCount;
	return (
		<div className="text-[12px]">
			<p className="font-semibold text-foreground">Conversation activity</p>
			<dl className="mt-2 space-y-1.5 tabular-nums">
				<div className="flex items-center justify-between gap-8">
					<dt className="text-subtle">Your messages</dt>
					<dd>{humanCount}</dd>
				</div>
				<div className="flex items-center justify-between gap-8">
					<dt className="text-subtle">Assistant messages</dt>
					<dd>{assistantCount}</dd>
				</div>
				<div className="flex items-center justify-between gap-8 border-t border-border pt-1.5">
					<dt className="text-subtle">Completed tool calls</dt>
					<dd>{finishedCount}</dd>
				</div>
				{failedCount > 0 && (
					<div className="flex items-center justify-between gap-8">
						<dt className="text-subtle">Failed tool calls</dt>
						<dd>{failedCount}</dd>
					</div>
				)}
				{incompleteCount > 0 && (
					<div className="flex items-center justify-between gap-8">
						<dt className="text-subtle">Incomplete tool calls</dt>
						<dd>{incompleteCount}</dd>
					</div>
				)}
			</dl>
			<p className="mt-2 leading-5 text-meta">
				A tool call is one action requested from an MCP server or the sandbox.
			</p>
		</div>
	);
}

function SharedFile({
	artifact,
	shareId,
	token,
}: {
	artifact: PublicConversationArtifact;
	shareId: string;
	token: string;
}) {
	const [imageUrl, setImageUrl] = useState<string | null>(null);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState(false);

	useEffect(() => {
		if (!artifact.mime_type.startsWith("image/")) return;
		let active = true;
		let objectUrl: string | null = null;
		void getPublicArtifact(shareId, artifact.id, token).then(
			async (blob) => {
				const typed = new Blob([await blob.arrayBuffer()], {
					type: artifact.mime_type,
				});
				objectUrl = URL.createObjectURL(typed);
				if (active) setImageUrl(objectUrl);
			},
			() => {
				if (active) setError(true);
			},
		);
		return () => {
			active = false;
			if (objectUrl) URL.revokeObjectURL(objectUrl);
		};
	}, [artifact.id, artifact.mime_type, shareId, token]);

	const download = async () => {
		setBusy(true);
		setError(false);
		try {
			const blob = await getPublicArtifact(shareId, artifact.id, token);
			const url = URL.createObjectURL(blob);
			const anchor = document.createElement("a");
			anchor.href = url;
			anchor.download = artifact.filename;
			anchor.click();
			setTimeout(() => {
				URL.revokeObjectURL(url);
			}, 0);
		} catch {
			setError(true);
		} finally {
			setBusy(false);
		}
	};

	return (
		<div className="w-full max-w-sm overflow-hidden rounded-[10px] border border-border bg-card">
			{imageUrl && (
				<Image
					unoptimized
					src={imageUrl}
					alt={artifact.title}
					className="max-h-72 w-full bg-hover object-contain"
					height={288}
					width={640}
				/>
			)}
			<div className="flex items-center gap-3 p-3">
				<span className="flex size-9 shrink-0 items-center justify-center rounded-[8px] bg-hover text-petrol">
					{artifact.mime_type.startsWith("image/") ? (
						<ImageIcon className="size-4" />
					) : (
						<FileText className="size-4" />
					)}
				</span>
				<div className="min-w-0 flex-1">
					<p className="truncate text-[12.5px] font-semibold text-foreground">
						{artifact.title}
					</p>
					<p className="text-[11px] text-meta">
						{formatBytes(artifact.size)}
						{error ? " / Unavailable" : ""}
					</p>
				</div>
				<button
					type="button"
					disabled={busy}
					onClick={() => {
						void download();
					}}
					className="flex size-8 cursor-pointer items-center justify-center rounded-[7px] border border-input text-subtle transition-colors hover:bg-hover hover:text-foreground disabled:opacity-50"
					aria-label={`Download ${artifact.filename}`}
				>
					<Download className="size-3.5" />
				</button>
			</div>
		</div>
	);
}

type PublicToolIdentity = {
	serverName: string;
	toolName: string;
	icon?: string;
	iconKind?: "web";
};

function ToolCall({
	call,
	describe,
}: {
	call: ToolCallView;
	describe: (name: string) => PublicToolIdentity;
}) {
	const result = call.error ?? call.output;
	const { serverName, toolName, icon, iconKind } = describe(call.name);
	return (
		<details className="my-2 rounded-[9px] border border-border bg-hover/30 dark:border-white/8 dark:bg-white/[0.035]">
			<summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-[12px] font-semibold text-subtle dark:text-panel-button">
				<ChainStepIcon
					icon={icon}
					name={serverName}
					fallback={
						iconKind === "web" ? (
							<Globe2 className="size-[13px] text-label" />
						) : undefined
					}
				/>
				{toolLabel(toolName)}
				<span className="ml-auto font-normal text-meta dark:text-panel-dim">
					{call.status === "error"
						? "Failed"
						: call.status === "running"
							? "Incomplete"
							: "Completed"}
				</span>
			</summary>
			<div className="space-y-2 border-t border-border p-3 dark:border-white/8">
				{call.args && Object.keys(call.args).length > 0 && (
					<div className="max-h-64 overflow-auto rounded-[7px] bg-background dark:bg-black/20">
						<CodeBlock
							code={printable(call.args)}
							language={printableLanguage(call.args)}
						/>
					</div>
				)}
				{result != null && (
					<div className="max-h-80 overflow-auto rounded-[7px] bg-background dark:bg-black/20">
						<CodeBlock
							code={printable(result)}
							language={printableLanguage(result)}
						/>
					</div>
				)}
				{call.truncatedChars !== undefined && (
					<p className="text-[11px] text-meta">
						Showing a preview. The original result contains{" "}
						{call.truncatedChars.toLocaleString()} characters.
					</p>
				)}
			</div>
		</details>
	);
}

function PublicTranscript({
	conversation,
	messages,
	shareId,
	token,
}: {
	conversation: PublicConversation;
	messages: BaseMessage[];
	shareId: string;
	token: string;
}) {
	const toolCalls = useMemo(() => pairToolCalls(messages), [messages]);
	const runMetadataByUserTurn = useMemo(
		() => mapRunMetadataToUserTurns(messages, conversation.runs ?? []),
		[conversation.runs, messages],
	);
	const toolsByMessage = useMemo(() => {
		const grouped = new Map<string, ToolCallView[]>();
		for (const call of toolCalls) {
			if (!call.messageId) continue;
			grouped.set(call.messageId, [
				...(grouped.get(call.messageId) ?? []),
				call,
			]);
		}
		return grouped;
	}, [toolCalls]);
	const describeTool = useMemo(() => {
		const toolServers = conversation.tool_servers ?? [];
		const knownServerNames = toolServers
			.filter((server) => server.tool_names === undefined)
			.map((server) => server.name)
			.sort((a, b) => b.length - a.length);
		return (name: string): PublicToolIdentity => {
			const exactServer = toolServers.find((server) =>
				server.tool_names?.includes(name),
			);
			if (exactServer) {
				return {
					serverName: exactServer.name,
					toolName: getToolMetadata(name, [exactServer.name]).toolName,
					icon: exactServer.icon_url ?? undefined,
				};
			}
			if (isSandboxTool(name)) {
				return {
					serverName: "Code execution",
					toolName: name,
				};
			}
			if (/^(?:web_search|google_search)(?:_\d+)?$/.test(name)) {
				return {
					serverName: "Web search",
					toolName: "web_search",
					iconKind: "web",
				};
			}
			if (/^(?:search_mcp_tools|load_mcp_tools)(?:_\d+)?$/.test(name)) {
				return {
					serverName: "Precision",
					toolName: name.startsWith("search_") ? "find_tools" : "load_tools",
					icon: "/pwa-icon.svg",
				};
			}
			const { serverName, toolName } = getToolMetadata(
				name,
				knownServerNames,
			);
			const server = toolServers.find(
				(candidate) => candidate.name === serverName,
			);
			return {
				serverName,
				toolName,
				icon: server?.icon_url ?? undefined,
			};
		};
	}, [conversation.tool_servers]);
	const artifactsById = useMemo(
		() => new Map(conversation.artifacts.map((item) => [item.id, item])),
		[conversation.artifacts],
	);
	const loadImage = useCallback(
		async (imageId: string) => {
			const blob = await getPublicArtifact(shareId, imageId, token).catch(
				() => {
					throw new Error("This shared image is unavailable.");
				},
			);
			return new Blob([await blob.arrayBuffer()], { type: "image/webp" });
		},
		[shareId, token],
	);
	const artifactsByToolCall = useMemo(() => {
		const grouped = new Map<string, PublicConversationArtifact[]>();
		for (const artifact of conversation.artifacts) {
			if (!artifact.tool_call_id) continue;
			grouped.set(artifact.tool_call_id, [
				...(grouped.get(artifact.tool_call_id) ?? []),
				artifact,
			]);
		}
		return grouped;
	}, [conversation.artifacts]);

	return messages.map((message: BaseMessage, index) => {
		if (isToolMessage(message)) return null;
		if (isHumanMessage(message)) {
			const runMetadata = runMetadataByUserTurn.get(
				userTurnKey(message, index),
			);
			const promptLabel = runMetadata
				? formatPromptTimestamp(runMetadata.promptedAt)
				: null;
			const durationLabel =
				runMetadata?.durationMs != null
					? formatDuration(runMetadata.durationMs)
					: null;
			const metadataTitle = [
				promptLabel ? `Prompt sent: ${promptLabel}` : null,
				durationLabel ? `Response time: ${durationLabel}` : null,
			]
				.filter(Boolean)
				.join(". ");
			const inline = getFileAttachments(message);
			const displayText = message.additional_kwargs?.display_text;
			const text =
				typeof displayText === "string" ? displayText : message.text;
			const persistent = getAttachmentIds(message)
				.map((id) => artifactsById.get(id))
				.filter(
					(item): item is PublicConversationArtifact => item !== undefined,
				);
			const persistentFiles = new Set(
				persistent.map(
					(artifact) => `${artifact.filename}\0${artifact.mime_type}`,
				),
			);
			const visibleInline = inline.filter(
				(file) =>
					!persistentFiles.has(
						`${file.filename ?? ""}\0${file.mediaType}`,
					),
			);
			return (
				<Message
					key={message.id ?? index}
					id={threadMapAnchor(index)}
					from="user"
					className="py-2"
				>
					<MessageContent>
						{text && <MessageResponse>{text}</MessageResponse>}
						{visibleInline.map((file) =>
							"url" in file && file.url ? (
								<a
									key={file.id}
									href={file.url}
									download={file.filename}
									className="mt-2 block text-[12px] font-medium text-primary underline"
								>
									{file.filename}
								</a>
							) : null,
						)}
						{persistent.map((artifact) => (
							<SharedFile
								key={artifact.id}
								artifact={artifact}
								shareId={shareId}
								token={token}
							/>
						))}
					</MessageContent>
					{(promptLabel || durationLabel) && (
						<div
							className="ml-auto flex items-center gap-1 pr-0.5 font-mono text-[10px] leading-none tabular-nums text-meta dark:text-panel-dim"
							title={metadataTitle}
							aria-label={metadataTitle}
						>
							{promptLabel && (
								<time
									dateTime={runMetadata?.promptedAt}
									suppressHydrationWarning
								>
									{promptLabel}
								</time>
							)}
							{promptLabel && durationLabel && (
								<span aria-hidden="true">/</span>
							)}
							{durationLabel && (
								<>
									<Clock3 aria-hidden="true" className="size-2.5" />
									<span>{durationLabel}</span>
								</>
							)}
						</div>
					)}
				</Message>
			);
		}
		if (!isAIMessage(message)) return null;
		const reasoning = getReasoning(message);
		const calls = message.id ? (toolsByMessage.get(message.id) ?? []) : [];
		if (!reasoning && calls.length === 0 && !message.text) return null;
		return (
			<div key={message.id ?? index} className="py-2">
				{reasoning && (
					<details className="mb-3 text-[12px] text-subtle">
						<summary className="cursor-pointer font-medium">Reasoning</summary>
						<div className="mt-2 whitespace-pre-wrap border-l border-border pl-3">
							{reasoning}
						</div>
					</details>
				)}
				{calls.map((call) => {
					const gallery = getImageGallery(call.artifact);
					const galleryIds = new Set(gallery?.images.map((image) => image.id));
					return (
						<div key={call.id}>
							<ToolCall call={call} describe={describeTool} />
							{gallery && <ImageGallery gallery={gallery} load={loadImage} />}
							{(artifactsByToolCall.get(call.callId ?? call.id) ?? [])
								.filter((artifact) => !galleryIds.has(artifact.id))
								.map((artifact) => (
									<SharedFile
										key={artifact.id}
										artifact={artifact}
										shareId={shareId}
										token={token}
									/>
								))}
						</div>
					);
				})}
				{message.text && (
					<Message from="assistant">
						<MessageContent>
							<MessageResponse>{message.text}</MessageResponse>
						</MessageContent>
					</Message>
				)}
			</div>
		);
	});
}

export function PublicConversationView({ shareId }: { shareId: string }) {
	const [state, setState] = useState<
		| { status: "loading" }
		| { status: "error" }
		| { status: "ready"; conversation: PublicConversation; token: string }
	>({ status: "loading" });

	useEffect(() => {
		const token = new URLSearchParams(window.location.hash.slice(1)).get(
			"token",
		);
		let active = true;
		const request = token
			? getPublicConversation(shareId, token)
			: Promise.reject(new Error("Missing share token"));
		void request.then(
			(conversation) => {
				if (active && token) {
					setState({ status: "ready", conversation, token });
				}
			},
			() => {
				if (active) setState({ status: "error" });
			},
		);
		return () => {
			active = false;
		};
	}, [shareId]);

	if (state.status === "loading") {
		return (
			<main className="flex min-h-dvh items-center justify-center bg-background">
				<div className="h-8 w-40 animate-pulse rounded-full bg-hover" />
			</main>
		);
	}
	if (state.status === "error") {
		return (
			<main className="flex min-h-dvh items-center justify-center bg-background p-6">
				<div className="max-w-sm text-center">
					<LockKeyhole className="mx-auto size-8 text-meta" />
					<h1 className="mt-4 text-[18px] font-semibold text-foreground">
						Conversation unavailable
					</h1>
					<p className="mt-2 text-[13px] leading-5 text-subtle">
						This link is invalid or the publication has been removed.
					</p>
				</div>
			</main>
		);
	}

	const { conversation, token } = state;
	const messages = conversation.messages.map((message) =>
		coerceMessageLikeToMessage(message as BaseMessageLike),
	);
	const humanMessageCount = messages.filter(isHumanMessage).length;
	const assistantMessageCount = messages.filter(isAIMessage).length;
	const messageCount = humanMessageCount + assistantMessageCount;
	const toolCalls = pairToolCalls(messages);
	const toolCount = toolCalls.length;
	const modelLabel = conversation.model_name ?? conversation.model_id;
	const cost = conversation.cost;
	const costLabel =
		cost && cost.call_count > 0
			? cost.unpriced_call_count === cost.call_count
				? "Cost unavailable"
				: `${cost.complete ? "" : "≥"}${formatCost(cost.known_cost)}`
			: null;
	const publishedLabel = conversation.published_at
		? new Intl.DateTimeFormat(undefined, {
				dateStyle: "medium",
				timeStyle: "short",
			}).format(new Date(conversation.published_at))
		: null;
	return (
		<main className="flex h-dvh flex-col bg-background">
			<header className="flex min-h-14 shrink-0 items-center justify-between gap-4 border-b border-border px-4 py-2 md:px-6 dark:border-white/8">
				<div className="flex min-w-0 items-center gap-2.5">
					<span
						className="flex size-8 shrink-0 items-center justify-center rounded-full text-sm"
						style={{ backgroundColor: conversation.agent.color ?? undefined }}
					>
						{conversation.agent.emoji ?? "A"}
					</span>
					<div className="min-w-0">
						<p className="truncate text-[13px] font-semibold text-foreground">
							{conversation.agent.name}
						</p>
						{publishedLabel && (
							<p className="truncate text-[11px] text-meta dark:text-panel-dim">
								Published {publishedLabel}
							</p>
						)}
					</div>
				</div>
				<div className="flex min-w-0 items-center justify-start gap-1.5 overflow-x-auto pl-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
					{modelLabel && (
						<HoverCard openDelay={150} closeDelay={100}>
							<HoverCardTrigger asChild>
								<span
									tabIndex={costLabel ? 0 : undefined}
									className="flex h-[30px] shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border border-border bg-card px-2.5 text-[11.5px] font-medium text-subtle outline-none focus-visible:ring-2 focus-visible:ring-petrol/40 dark:border-white/8 dark:bg-white/5 dark:text-panel-body"
								>
									<Cpu className="size-3.5" />
									<span className="max-w-40 truncate">{modelLabel}</span>
									{costLabel && (
										<span className="border-l border-border pl-1.5 tabular-nums dark:border-white/10">
											{costLabel}
										</span>
									)}
								</span>
							</HoverCardTrigger>
							{cost && cost.call_count > 0 && (
								<HoverCardContent align="end" className="w-80">
									<PublicCostBreakdown cost={cost} />
								</HoverCardContent>
							)}
						</HoverCard>
					)}
					{conversation.memories_enabled != null && (
						<span
							className={`flex h-[30px] shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 text-[11.5px] font-medium ${
								conversation.memories_enabled
									? "border-petrol/25 bg-petrol/8 text-petrol dark:border-panel-terminal/25 dark:bg-panel-terminal/10 dark:text-panel-terminal"
									: "border-border bg-card text-meta dark:border-white/8 dark:bg-white/5 dark:text-panel-dim"
							}`}
						>
							<Brain className="size-3.5" />
							Memories {conversation.memories_enabled ? "on" : "off"}
						</span>
					)}
					<HoverCard openDelay={150} closeDelay={100}>
						<HoverCardTrigger asChild>
							<span
								tabIndex={0}
								aria-label={`${messageCount} messages and ${toolCount} tool calls`}
								className="flex h-[30px] shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border border-border px-2.5 text-[11.5px] font-medium text-subtle outline-none focus-visible:ring-2 focus-visible:ring-petrol/40 dark:border-white/8 dark:text-panel-body"
							>
								<MessageSquare className="size-3.5" />
								{messageCount} messages
								{toolCount > 0 && <span>/ {toolCount} calls</span>}
							</span>
						</HoverCardTrigger>
						<HoverCardContent align="end" className="w-72">
							<ActivityBreakdown
								humanCount={humanMessageCount}
								assistantCount={assistantMessageCount}
								toolCalls={toolCalls}
							/>
						</HoverCardContent>
					</HoverCard>
					<span className="flex h-[30px] shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border border-border px-2.5 text-[11.5px] font-medium text-subtle dark:border-white/8 dark:text-panel-body">
						<Globe2 className="size-3.5" />
						Read-only
					</span>
				</div>
			</header>
			<div className="relative flex min-h-0 flex-1">
				<Conversation
					initial={false}
					showScrollbar
					className="min-h-0 flex-1"
				>
					<ConversationContent className="mx-auto w-full max-w-4xl gap-2 px-3 pb-16 sm:px-6 lg:px-10">
						<PublicTranscript
							conversation={conversation}
							messages={messages}
							shareId={shareId}
							token={token}
						/>
					</ConversationContent>
				</Conversation>
				<ThreadMap messages={messages} />
			</div>
		</main>
	);
}
