"use client";

import type { BaseMessage } from "@langchain/core/messages";
import { isAIMessage } from "@langchain/core/messages";
import { cn } from "@/lib/utils";

// Written by the backend's ContextFootprintMiddleware on every model answer:
// what the request was made of, estimated per part and scaled to the
// provider-reported input total.
interface ContextFootprint {
	context_window: number | null;
	input_tokens: number;
	measured: boolean;
	system: number;
	tools: number;
	messages: number;
	tools_loaded: number;
	tools_available: number;
	tools_hidden: number;
}

export interface ContextUsage extends ContextFootprint {
	contextWindow: number | null;
	percent: number | null;
	harness: number;
	reasoningTokens: number;
	outputTokens: number;
	cachedTokens: number;
}

const WARNING_PERCENT = 80;

const isFootprint = (value: unknown): value is ContextFootprint =>
	typeof value === "object" &&
	value !== null &&
	typeof (value as ContextFootprint).input_tokens === "number" &&
	typeof (value as ContextFootprint).system === "number";

export function contextUsage(
	messages: BaseMessage[] | undefined,
	contextWindow: number | null | undefined,
): ContextUsage | null {
	if (!messages) return null;
	for (let index = messages.length - 1; index >= 0; index -= 1) {
		const message = messages[index];
		if (!isAIMessage(message)) continue;
		const metadata = message.response_metadata as
			| Record<string, unknown>
			| undefined;
		const footprint = metadata?.context_footprint;
		if (!isFootprint(footprint)) continue;
		const window = contextWindow ?? footprint.context_window ?? null;
		const usage = message.usage_metadata;
		return {
			...footprint,
			contextWindow: window,
			percent: window
				? Math.min(100, (footprint.input_tokens / window) * 100)
				: null,
			harness: footprint.system + footprint.tools,
			reasoningTokens: usage?.output_token_details?.reasoning ?? 0,
			outputTokens: usage?.output_tokens ?? 0,
			cachedTokens: usage?.input_token_details?.cache_read ?? 0,
		};
	}
	return null;
}

const compact = new Intl.NumberFormat("en-US", {
	notation: "compact",
	maximumFractionDigits: 1,
});
const exact = new Intl.NumberFormat("en-US");

export const formatCompactTokens = (value: number) => compact.format(value);

const formatPercent = (value: number) =>
	value > 0 && value < 1
		? "<1%"
		: value > 99 && value < 100
			? ">99%"
			: `${Math.round(value)}%`;

export const contextGaugeLabel = (usage: ContextUsage) =>
	usage.percent === null
		? formatCompactTokens(usage.input_tokens)
		: formatPercent(usage.percent);

export const ContextRing = ({
	percent,
	className,
}: {
	percent: number | null;
	className?: string;
}) => {
	const radius = 6;
	const circumference = 2 * Math.PI * radius;
	const filled = ((percent ?? 0) / 100) * circumference;
	return (
		<svg
			viewBox="0 0 16 16"
			aria-hidden="true"
			className={cn("size-4 -rotate-90", className)}
		>
			<circle
				cx="8"
				cy="8"
				r={radius}
				fill="none"
				strokeWidth="2.5"
				className="stroke-current opacity-20"
			/>
			<circle
				cx="8"
				cy="8"
				r={radius}
				fill="none"
				strokeWidth="2.5"
				strokeLinecap="round"
				strokeDasharray={`${filled} ${circumference}`}
				className={cn(
					"stroke-current",
					percent !== null && percent >= WARNING_PERCENT && "text-warning",
				)}
			/>
		</svg>
	);
};

const SEGMENTS = [
	{
		key: "system",
		label: "System prompt",
		className: "bg-petrol dark:bg-panel-terminal",
	},
	{
		key: "tools",
		label: "Tool definitions",
		className: "bg-petrol/55 dark:bg-panel-terminal/55",
	},
	{
		key: "messages",
		label: "Conversation",
		className: "bg-petrol/35 dark:bg-panel-terminal/35",
	},
] as const;

export const ContextUsagePanel = ({
	usage,
	modelName,
	effortLabel,
	toolModeLabel,
}: {
	usage: ContextUsage;
	modelName?: string;
	effortLabel?: string;
	toolModeLabel?: string;
}) => {
	const total = usage.contextWindow ?? usage.input_tokens;
	const share = (value: number) =>
		total > 0 ? `${Math.max(0, (value / total) * 100)}%` : "0%";
	const harnessShare =
		usage.input_tokens > 0 ? (usage.harness / usage.input_tokens) * 100 : 0;

	return (
		<div className="w-[340px] max-w-[calc(100vw-2rem)] p-4">
			<div className="flex items-baseline justify-between gap-3">
				<h3 className="text-[13px] font-semibold text-foreground">
					Context window
				</h3>
				{modelName && (
					<span className="truncate text-[11.5px] text-meta dark:text-panel-dim">
						{modelName}
					</span>
				)}
			</div>
			<p className="mt-1 font-mono text-[12px] text-body dark:text-panel-body">
				{exact.format(usage.input_tokens)}
				{usage.contextWindow !== null && (
					<>
						{" "}
						/ {exact.format(usage.contextWindow)} tokens
						{usage.percent !== null && ` (${formatPercent(usage.percent)})`}
					</>
				)}
				{usage.contextWindow === null && " tokens"}
			</p>

			<div
				className="mt-3 flex h-2 w-full overflow-hidden rounded-full bg-hover dark:bg-white/10"
				role="img"
				aria-label="Context window usage by source"
			>
				{SEGMENTS.map((segment) => (
					<div
						key={segment.key}
						className={segment.className}
						style={{ width: share(usage[segment.key]) }}
					/>
				))}
			</div>

			<div className="mt-3 flex flex-col gap-1.5">
				{SEGMENTS.map((segment) => (
					<UsageRow
						key={segment.key}
						swatch={segment.className}
						label={segment.label}
						value={usage[segment.key]}
						hint={
							segment.key === "tools"
								? toolsHint(usage, toolModeLabel)
								: segment.key === "system"
									? "Instructions, MCP server context, skills and harness"
									: undefined
						}
					/>
				))}
			</div>

			<div className="mt-3 rounded-[8px] bg-hover px-3 py-2.5 text-[11.5px] leading-[1.5] text-meta dark:bg-white/5 dark:text-panel-dim">
				<span className="font-semibold text-body dark:text-panel-body">
					Harness footprint: {exact.format(usage.harness)} tokens
				</span>{" "}
				({formatPercent(harnessShare)} of the last request), sent again with
				every model call.
				{usage.tools_hidden > 0 && (
					<>
						{" "}
						Loading every tool would add about{" "}
						{formatCompactTokens(usage.tools_hidden)} tokens.
					</>
				)}
			</div>

			<div className="mt-3 flex flex-col gap-1.5 border-t border-hairline pt-3 dark:border-white/5">
				<UsageRow
					label="Reasoning (last answer)"
					value={usage.reasoningTokens}
					hint={effortLabel ? `Effort: ${effortLabel}` : undefined}
				/>
				<UsageRow label="Output (last answer)" value={usage.outputTokens} />
				{usage.cachedTokens > 0 && (
					<UsageRow label="Read from cache" value={usage.cachedTokens} />
				)}
			</div>

			{usage.percent !== null && usage.percent >= WARNING_PERCENT && (
				<p className="mt-3 rounded-[8px] bg-warning-bg px-3 py-2 text-[11.5px] leading-[1.5] text-warning">
					This conversation is close to the model&apos;s limit. Start a new
					conversation or switch to a model with a larger context window.
				</p>
			)}

			<p className="mt-3 text-[10.5px] leading-[1.5] text-meta dark:text-panel-dim">
				{usage.measured
					? "Last model request, as reported by the provider. The split by source is estimated."
					: "Estimated: the provider reported no usage for the last request."}
				{usage.contextWindow === null &&
					" The context window of this model is unknown."}
			</p>
		</div>
	);
};

const toolsHint = (usage: ContextUsage, toolModeLabel?: string) => {
	const loaded = `${usage.tools_loaded} of ${usage.tools_available} tools loaded`;
	return toolModeLabel ? `${loaded} / ${toolModeLabel} mode` : loaded;
};

const UsageRow = ({
	label,
	value,
	hint,
	swatch,
}: {
	label: string;
	value: number;
	hint?: string;
	swatch?: string;
}) => (
	<div className="flex items-start justify-between gap-3">
		<div className="flex min-w-0 items-start gap-2">
			{swatch && (
				<span className={cn("mt-[5px] size-2 shrink-0 rounded-[2px]", swatch)} />
			)}
			<div className="min-w-0">
				<div className="text-[12px] font-medium text-body dark:text-panel-body">
					{label}
				</div>
				{hint && (
					<div className="text-[10.5px] leading-tight text-meta dark:text-panel-dim">
						{hint}
					</div>
				)}
			</div>
		</div>
		<span className="shrink-0 font-mono text-[12px] font-semibold text-foreground">
			{exact.format(value)}
		</span>
	</div>
);
