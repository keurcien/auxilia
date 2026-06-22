"use client";

import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { Agent } from "@/types/agents";
import { agentColorBackground } from "@/lib/colors";

interface AgentDialogShellProps {
	agent: Agent;
	// Secondary line under the agent name (e.g. the @handle, or "Archived").
	subtitle: React.ReactNode;
	onClose: () => void;
	// When true, overlay/close-button clicks are ignored (e.g. while a request
	// is in flight).
	closeDisabled?: boolean;
	children: React.ReactNode;
}

// Shared modal chrome for agent dialogs: a centered portal with a blurred
// overlay, the rounded card container, and the avatar/name/subtitle/close
// header. Both the active-agent modal (AgentCard) and the archived-agent
// dialog render their body as children so the chrome stays consistent.
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
			className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(30,45,40,0.2)] backdrop-blur-[4px] animate-in fade-in duration-200"
			onClick={close}
		>
			<div
				className="bg-white dark:bg-card rounded-[28px] p-8 w-[440px] max-w-[90vw] shadow-[0_24px_48px_-12px_rgba(0,0,0,0.12)] animate-in slide-in-from-bottom-4 zoom-in-[0.97] duration-300"
				onClick={(e) => {
					e.stopPropagation();
				}}
			>
				{/* Avatar + Name + Close */}
				<div className="flex items-center gap-4 mb-6">
					<div
						style={{
							background: agentColorBackground(color),
							border: `1.5px solid ${color}18`,
						}}
						className="shrink-0 w-[60px] h-[60px] rounded-full flex items-center justify-center text-[30px]"
					>
						{agent.emoji || "🤖"}
					</div>
					<div className="flex-1 min-w-0">
						<div className="font-[family-name:var(--font-jakarta-sans)] text-[20px] font-extrabold text-[#1E2D28] dark:text-foreground tracking-[-0.02em] truncate">
							{agent.name}
						</div>
						<div className="font-[family-name:var(--font-dm-sans)] text-[13.5px] text-[#A3B5AD] dark:text-muted-foreground font-medium mt-0.5">
							{subtitle}
						</div>
					</div>
					<button
						onClick={close}
						className="shrink-0 self-start w-9 h-9 rounded-full bg-[#F5F8F6] dark:bg-white/10 flex items-center justify-center cursor-pointer transition-colors hover:bg-[#EDF4F0] dark:hover:bg-white/15"
					>
						<X className="h-4 w-4 text-[#6B7F76]" />
					</button>
				</div>

				{children}
			</div>
		</div>,
		document.body,
	);
}
