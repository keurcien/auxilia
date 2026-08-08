"use client";

import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { humanizeToolName } from "@/components/ai-elements/chain-of-thought";

const SANDBOX_TOOLS = [
	{ name: "ls", description: "List files in a directory with metadata (size, modified time)" },
	{ name: "read_file", description: "Read file contents with line numbers, supports offset/limit for large files" },
	{ name: "write_file", description: "Create new files" },
	{ name: "edit_file", description: "Perform exact string replacements in files (with global replace mode)" },
	{ name: "glob", description: "Find files matching patterns (e.g., **/*.py)" },
	{ name: "grep", description: "Search file contents with multiple output modes (files only, content with context, or counts)" },
	{ name: "execute", description: "Run shell commands in the environment" },
];

interface AgentCodeExecutionProps {
	readOnly?: boolean;
	/** Draft update: turn the code interpreter off. */
	onDisable?: () => void;
}

export default function AgentCodeExecution({
	readOnly,
	onDisable,
}: AgentCodeExecutionProps) {
	const [isExpanded, setIsExpanded] = useState(false);

	return (
		<div className="overflow-hidden rounded-[10px] border border-border bg-card">
			<div className="flex items-center gap-2.5 px-4 py-3">
				<span className="flex size-[26px] shrink-0 items-center justify-center rounded-[6px] bg-petrol-tint text-[13px]">
					🧮
				</span>
				<span className="text-[13.5px] font-semibold text-foreground">
					Code interpreter
				</span>
				<span className="text-xs text-meta dark:text-panel-dim">built-in</span>
				<span className="ml-auto flex items-center gap-1.5">
					{!readOnly && (
						<button
							className="cursor-pointer rounded-[7px] px-2.5 py-1 text-[12.5px] font-semibold text-[#B04A3A] transition-colors hover:bg-[#FBEFED] dark:hover:bg-[#B04A3A]/10"
							onClick={() => {
								onDisable?.();
							}}
						>
							Disable
						</button>
					)}
					<button
						onClick={() => {
							setIsExpanded(!isExpanded);
						}}
						aria-label={isExpanded ? "Collapse" : "Expand"}
						className="cursor-pointer p-1 text-meta transition-colors hover:text-foreground dark:text-panel-dim"
					>
						<ChevronRight
							className={`size-4 transition-transform ${
								isExpanded ? "rotate-90" : ""
							}`}
						/>
					</button>
				</span>
			</div>

			{isExpanded && (
				<div className="border-t border-hover dark:border-white/5">
					{SANDBOX_TOOLS.map((tool) => (
						<div
							key={tool.name}
							className="border-b border-hover px-4 py-2.5 last:border-b-0 dark:border-white/5"
						>
							<span className="block truncate text-[13.5px] font-semibold text-foreground">
								{humanizeToolName(tool.name)}
							</span>
							<span className="mt-px block text-xs text-muted-foreground">
								{tool.description}
							</span>
						</div>
					))}
				</div>
			)}
		</div>
	);
}
