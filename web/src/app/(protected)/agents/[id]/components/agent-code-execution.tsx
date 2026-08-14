"use client";

import { useState } from "react";
import Image from "next/image";
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
	// Matches the MCP server cards: collapsed on page open.
	const [isExpanded, setIsExpanded] = useState(false);

	return (
		<div className="overflow-hidden rounded-[10px] border border-border bg-card">
			<div className="flex items-center gap-2.5 bg-card px-4 py-3">
				<span className="flex size-[26px] shrink-0 items-center justify-center rounded-[6px] border border-border bg-card">
					<Image
						unoptimized
						width={14}
						height={14}
						src="https://pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev/assets/icons/terminal.png"
						alt="Code execution"
						className="rounded-[2px] object-contain"
					/>
				</span>
				<span className="text-[13.5px] font-semibold text-foreground">
					Code execution
				</span>
				<button
					onClick={() => {
						setIsExpanded(!isExpanded);
					}}
					aria-label={isExpanded ? "Collapse" : "Expand"}
					aria-expanded={isExpanded}
					className="ml-auto cursor-pointer p-1 text-meta transition-colors hover:text-foreground dark:text-panel-dim"
				>
					<ChevronRight
						className={`size-4 transition-transform ${
							isExpanded ? "rotate-90" : ""
						}`}
					/>
				</button>
			</div>

			{isExpanded && (
				<div className="border-t border-hover dark:border-white/5">
					<div className="max-h-80 overflow-y-auto [scrollbar-width:thin]">
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
					{!readOnly && (
						<div className="flex justify-center border-t border-hover px-4 py-2 dark:border-white/5">
							<button
								className="cursor-pointer rounded-[7px] px-3 py-1.5 text-[12.5px] font-semibold text-[#B04A3A] transition-colors hover:bg-[#FBEFED] dark:hover:bg-[#B04A3A]/10"
								onClick={() => {
									onDisable?.();
								}}
							>
								Disable Code execution
							</button>
						</div>
					)}
				</div>
			)}
		</div>
	);
}
