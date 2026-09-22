"use client";

import { useRef, useState } from "react";
import Image from "next/image";
import { Check, Copy } from "lucide-react";
import { MCPServer, MCPServerTool } from "@/types/mcp-servers";
import { ToolStatus } from "@/types/agents";
import {
	Dialog,
	DialogButton,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { humanizeToolName } from "@/components/ai-elements/chain-of-thought";
import { cn } from "@/lib/utils";

const TOOL_STATUS_LABELS = new Map<ToolStatus, string>([
	["always_allow", "Always allowed"],
	["needs_approval", "Needs approval"],
	["disabled", "Disabled"],
]);

export function toolStatusLabel(status: ToolStatus): string {
	return TOOL_STATUS_LABELS.get(status) ?? status;
}

const SUBTITLE = "List of all tools available in the MCP server.";

/**
 * The Markdown the dialog copies: an h1 for the server, the subtitle, then
 * one h2 per tool — business-friendly name, a hyphen, the approval status —
 * followed by the tool's full description.
 */
export function buildToolsMarkdown(
	serverName: string,
	tools: MCPServerTool[],
	statusFor: (toolName: string) => ToolStatus,
): string {
	const sections = tools.map((tool) => {
		const heading = `## ${humanizeToolName(tool.name)} - ${toolStatusLabel(statusFor(tool.name))}`;
		const description = tool.description?.trim();
		return description ? `${heading}\n\n${description}` : heading;
	});
	return [`# ${serverName} MCP server`, SUBTITLE, ...sections].join("\n\n") + "\n";
}

/**
 * Servers often hard-wrap descriptions at ~80 columns. Blank lines stay
 * paragraph breaks; single newlines collapse so text fills the dialog width.
 */
function descriptionParagraphs(description: string | null | undefined): string[] {
	const paragraphs = (description ?? "")
		.split(/\n\s*\n/)
		.map((paragraph) => paragraph.replace(/\s*\n\s*/g, " ").trim())
		.filter(Boolean);
	return paragraphs.length > 0 ? paragraphs : ["No description provided."];
}

interface MCPToolsDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	server: MCPServer;
	tools: MCPServerTool[];
	statusFor: (toolName: string) => ToolStatus;
}

/**
 * Full-description view of a server's tools — the panel rows clamp their
 * descriptions so the list stays scannable; this dialog shows every tool
 * with its complete description and approval status, and copies the whole
 * thing to the clipboard as Markdown.
 */
export default function MCPToolsDialog({
	open,
	onOpenChange,
	server,
	tools,
	statusFor,
}: MCPToolsDialogProps) {
	const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">(
		"idle",
	);
	const resetTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
	// Bumped on every copy and on close, so a clipboard promise that settles
	// after the dialog closed (or after a newer click) cannot touch the state.
	const copyRequest = useRef(0);

	const clearResetTimer = () => {
		if (resetTimer.current) clearTimeout(resetTimer.current);
		resetTimer.current = null;
	};

	const settleCopy = (request: number, state: "copied" | "failed") => {
		if (request !== copyRequest.current) return;
		setCopyState(state);
		clearResetTimer();
		resetTimer.current = setTimeout(() => {
			setCopyState("idle");
		}, 2000);
	};

	const handleOpenChange = (next: boolean) => {
		if (!next) {
			copyRequest.current += 1;
			clearResetTimer();
			setCopyState("idle");
		}
		onOpenChange(next);
	};

	const handleCopy = () => {
		const request = ++copyRequest.current;
		// navigator.clipboard is absent on insecure origins (self-hosted over
		// plain HTTP) even though the DOM types claim otherwise.
		const clipboard = navigator.clipboard as Clipboard | undefined;
		if (!clipboard) {
			settleCopy(request, "failed");
			return;
		}
		clipboard
			.writeText(buildToolsMarkdown(server.name, tools, statusFor))
			.then(() => {
				settleCopy(request, "copied");
			})
			.catch(() => {
				settleCopy(request, "failed");
			});
	};

	return (
		<Dialog open={open} onOpenChange={handleOpenChange}>
			<DialogContent className="flex max-h-[85vh] flex-col gap-0 p-0 sm:max-w-[760px]">
				<DialogHeader className="flex-row items-center gap-3 border-b border-hover px-6 py-5 dark:border-white/5">
					<span className="flex size-10 shrink-0 items-center justify-center rounded-[8px] border border-border bg-card">
						<Image
							unoptimized
							width={18}
							height={18}
							src={
								server.iconUrl ??
								"https://pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev/assets/icons/mcp.png"
							}
							alt={server.name}
							className="rounded-[2px] object-contain"
						/>
					</span>
					<div className="flex min-w-0 flex-col gap-0.5">
						<DialogTitle className="text-[18px]">
							{server.name} MCP server
						</DialogTitle>
						<DialogDescription className="font-mono text-[12px]">
							{SUBTITLE}
						</DialogDescription>
					</div>
				</DialogHeader>

				<div className="min-h-0 flex-1 overflow-y-auto [scrollbar-width:thin]">
					{tools.map((tool) => {
						const status = statusFor(tool.name);
						const isDisabled = status === "disabled";
						return (
							<section
								key={tool.name}
								className="border-b border-hover px-6 py-4 last:border-b-0 dark:border-white/5"
							>
								<div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
									<h3
										className={cn(
											"text-[15px] font-bold",
											isDisabled
												? "text-meta dark:text-panel-dim"
												: "text-foreground",
										)}
									>
										{humanizeToolName(tool.name)}
									</h3>
									<span className="font-mono text-[12px] text-petrol">
										{tool.name}
									</span>
									<span
										className={cn(
											"rounded-[4px] px-2 py-0.5 font-mono text-[9.5px] font-semibold tracking-[0.05em] uppercase",
											status === "always_allow" &&
												"bg-success-bg text-success",
											status === "needs_approval" &&
												"bg-hover text-label dark:bg-white/10 dark:text-panel-dim",
											isDisabled &&
												"bg-[#FBEFED] text-[#B04A3A] dark:bg-[#B04A3A]/10",
										)}
									>
										{toolStatusLabel(status)}
									</span>
								</div>
								<div
									className={cn(
										"mt-1.5 flex flex-col gap-2 text-[13.5px] leading-[1.55]",
										isDisabled
											? "text-faint dark:text-panel-dim"
											: "text-muted-foreground",
									)}
								>
									{descriptionParagraphs(tool.description).map(
										(paragraph, index) => (
											<p key={index}>{paragraph}</p>
										),
									)}
								</div>
							</section>
						);
					})}
				</div>

				<DialogFooter className="border-t border-hover px-6 py-4 dark:border-white/5">
					<DialogButton variant="outline" onClick={handleCopy}>
						{copyState === "copied" ? (
							<Check className="size-3.5" />
						) : (
							<Copy className="size-3.5" />
						)}
						{copyState === "copied"
							? "Copied"
							: copyState === "failed"
								? "Copy failed"
								: "Copy as Markdown"}
					</DialogButton>
					<DialogButton
						onClick={() => {
							handleOpenChange(false);
						}}
					>
						Close
					</DialogButton>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}
