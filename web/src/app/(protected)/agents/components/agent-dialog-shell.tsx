"use client";

import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { Agent } from "@/types/agents";
import { agentColorBackground } from "@/lib/colors";

interface AgentDialogShellProps {
	agent: Agent;
	subtitle: React.ReactNode;
	onClose: () => void;
	closeDisabled?: boolean;
	children: React.ReactNode;
}

export default function AgentDialogShell({
	agent,
	subtitle,
	onClose,
	closeDisabled = false,
	children,
}: AgentDialogShellProps) {
	const color = agent.color || "#9E9E9E";
	const close = () => {
		if (!closeDisabled) onClose();
	};

	return createPortal(
		<div
			className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(10,25,30,0.45)] animate-in fade-in duration-200"
			onClick={close}
		>
			<div
				className="w-[480px] max-w-[90vw] rounded-[14px] border border-hairline bg-canvas p-6 shadow-[0_24px_64px_-16px_rgba(10,25,30,0.28)] animate-in fade-in slide-in-from-bottom-2 duration-200 dark:bg-card"
				onClick={(e) => {
					e.stopPropagation();
				}}
			>
				<div className="mb-5 flex items-center gap-3.5">
					<div
						style={{
							background: agentColorBackground(color),
						}}
						className="flex size-12 shrink-0 items-center justify-center rounded-[12px] text-[24px]"
					>
						{agent.emoji || "🤖"}
					</div>
					<div className="min-w-0 flex-1">
						<div className="truncate text-[16px] leading-snug font-bold text-ink dark:text-panel-button">
							{agent.name}
						</div>
						<div className="mt-0.5 text-[13px] leading-[1.5] text-label dark:text-panel-dim">
							{subtitle}
						</div>
					</div>
					<button
						onClick={close}
						aria-label="Close"
						className="flex size-7 shrink-0 cursor-pointer items-center justify-center self-start rounded-[6px] text-meta transition-colors hover:bg-hover hover:text-ink dark:hover:bg-white/10 dark:hover:text-panel-button"
					>
						<X className="size-4" />
					</button>
				</div>

				{children}
			</div>
		</div>,
		document.body,
	);
}
