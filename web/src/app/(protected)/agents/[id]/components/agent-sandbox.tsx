"use client";

import { useState } from "react";
import Image from "next/image";
import { ChevronRight } from "lucide-react";
import { humanizeToolName } from "@/components/ai-elements/chain-of-thought";
import {
	SANDBOX_PROVIDER_ICONS,
	SANDBOX_PROVIDER_LABELS,
} from "@/lib/sandbox-providers";
import type { Sandbox } from "@/types/sandboxes";

const SANDBOX_TOOLS = [
	{ name: "create_sandbox", description: "Start a new code execution session" },
	{ name: "connect_sandbox", description: "Reattach to an existing session by ID" },
	{ name: "execute", description: "Run shell commands in the environment" },
	{ name: "ls", description: "List files in a directory with metadata (size, modified time)" },
	{ name: "read_file", description: "Read file contents with line numbers, supports offset/limit for large files" },
	{ name: "write_file", description: "Create new files" },
	{ name: "edit_file", description: "Perform exact string replacements in files (with global replace mode)" },
	{ name: "glob", description: "Find files matching patterns (e.g., **/*.py)" },
	{ name: "grep", description: "Search file contents with multiple output modes (files only, content with context, or counts)" },
];

interface AgentSandboxProps {
	sandbox: Sandbox;
	readOnly?: boolean;
	/** Draft update: detach this sandbox from the agent. */
	onRemove?: () => void;
}

export default function AgentSandbox({
	sandbox,
	readOnly,
	onRemove,
}: AgentSandboxProps) {
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
						src={SANDBOX_PROVIDER_ICONS[sandbox.provider]}
						alt={SANDBOX_PROVIDER_LABELS[sandbox.provider]}
						className="rounded-[2px] object-contain"
					/>
				</span>
				<span className="truncate text-[13.5px] font-semibold text-foreground">
					{sandbox.name}
				</span>
				<span className="shrink-0 rounded-[4px] bg-hover px-2 py-0.5 font-mono text-[9.5px] font-semibold tracking-[0.06em] text-subtle uppercase dark:bg-white/10 dark:text-panel-dim">
					{SANDBOX_PROVIDER_LABELS[sandbox.provider]}
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
									onRemove?.();
								}}
							>
								Disable {sandbox.name}
							</button>
						</div>
					)}
				</div>
			)}
		</div>
	);
}
