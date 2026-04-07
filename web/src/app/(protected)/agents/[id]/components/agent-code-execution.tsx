"use client";

import { useState } from "react";
import Image from "next/image";
import { ChevronRight } from "lucide-react";
import { Agent } from "@/types/agents";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";

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
	agent: Agent;
	onUpdate?: () => void;
	onSaving?: () => void;
	onSaved?: () => void;
}

export default function AgentCodeExecution({
	agent,
	onUpdate,
	onSaving,
	onSaved,
}: AgentCodeExecutionProps) {
	const [isExpanded, setIsExpanded] = useState(false);

	const handleDisable = async () => {
		onSaving?.();
		try {
			await api.patch(`/agents/${agent.id}`, { sandbox: false });
			onUpdate?.();
			onSaved?.();
		} catch (error) {
			console.error("Failed to disable code execution:", error);
			onSaved?.();
		}
	};

	return (
		<div className="border-b last:border-b-0">
			<div className="flex items-center p-3 hover:bg-[#F8FAF9] dark:hover:bg-white/5 transition-colors">
				<div className="w-6 h-6 rounded-sm flex items-center justify-center mr-3 overflow-hidden relative">
					<Image
						width={24}
						height={24}
						src="https://storage.googleapis.com/choose-assets/terminal.png"
						alt="Code execution"
						className="object-cover"
					/>
				</div>

				<div className="flex-1">
					<div className="flex items-center gap-2">
						<div className="font-[family-name:var(--font-dm-sans)] text-[14px] font-semibold text-[#1E2D28] dark:text-foreground">Code execution</div>
						<Badge
							variant="secondary"
							className="bg-green-100 dark:bg-green-950/40 text-green-600 dark:text-green-400 border-green-200 dark:border-green-800 text-[0.6rem]"
						>
							<span className="w-1.5 h-1.5 rounded-full bg-green-400" />
							Ready
						</Badge>
					</div>
				</div>

				<button
					onClick={() => setIsExpanded(!isExpanded)}
					className="text-muted-foreground hover:text-foreground cursor-pointer p-1"
				>
					<ChevronRight
						className={`w-5 h-5 transition-transform ${
							isExpanded ? "rotate-90" : ""
						}`}
					/>
				</button>
			</div>

			{isExpanded && (
				<div className="bg-card p-4 border-t">
					<div className="max-h-[400px] overflow-y-auto mb-3 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
						<div className="space-y-2">
							{SANDBOX_TOOLS.map((tool) => (
								<div
									key={tool.name}
									className="flex items-center p-3 bg-[#FAFCFB] rounded-2xl hover:bg-sidebar-hover border-[1.5px] border-[#E0E8E4] dark:border-white/10"
								>
									<div className="w-8 h-8 bg-white rounded-full flex items-center justify-center text-muted-foreground text-xs font-semibold mr-3 shrink-0 border-[1.5px] border-[#E0E8E4] dark:border-white/10">
										{tool.name.charAt(0).toUpperCase()}
									</div>
									<div className="flex-1 min-w-0 mr-3">
										<div className="font-[family-name:var(--font-dm-sans)] text-[14px] font-semibold text-[#1E2D28] dark:text-foreground truncate">
											{tool.name}
										</div>
										<div className="text-xs text-muted-foreground line-clamp-2">
											{tool.description}
										</div>
									</div>
								</div>
							))}
						</div>
					</div>
					<div className="flex w-full justify-center">
						<Button
							variant="ghost"
							size="sm"
							className="text-destructive cursor-pointer hover:text-destructive/80"
							onClick={handleDisable}
						>
							Disable Code execution
						</Button>
					</div>
				</div>
			)}
		</div>
	);
}
