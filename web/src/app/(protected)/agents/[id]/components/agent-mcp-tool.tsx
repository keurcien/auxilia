"use client";

import { ToolStatus } from "@/types/agents";
import { ThreeStateToggle } from "@/components/ui/three-state-toggle";
import { humanizeToolName } from "@/components/ai-elements/chain-of-thought";
import { cn } from "@/lib/utils";

interface AgentMCPToolProps {
	toolName: string;
	toolDescription?: string;
	status: ToolStatus;
	readOnly?: boolean;
	onStatusChange?: (status: ToolStatus) => void;
}

export default function AgentMCPTool({
	toolName,
	toolDescription,
	status,
	readOnly,
	onStatusChange,
}: AgentMCPToolProps) {
	const isDisabled = status === "disabled";

	return (
		<div className="flex items-center gap-2.5 border-b border-hover px-4 py-2.5 last:border-b-0 dark:border-white/5">
			<span className="min-w-0 flex-1">
				<span
					className={cn(
						"block truncate text-[13.5px] font-semibold",
						isDisabled ? "text-meta dark:text-panel-dim" : "text-foreground",
					)}
				>
					{humanizeToolName(toolName)}
				</span>
				{toolDescription && (
					<span
						className={cn(
							"mt-px line-clamp-2 text-xs",
							isDisabled
								? "text-faint dark:text-panel-dim"
								: "text-muted-foreground",
						)}
					>
						{toolDescription}
					</span>
				)}
			</span>

			<div
				className={`flex shrink-0 items-center ${
					readOnly ? "pointer-events-none opacity-60" : ""
				}`}
			>
				<ThreeStateToggle
					value={status}
					onChange={(value) => {
						if (!readOnly) onStatusChange?.(value);
					}}
				/>
			</div>
		</div>
	);
}
