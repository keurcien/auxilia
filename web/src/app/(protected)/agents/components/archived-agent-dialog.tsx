"use client";

import { useState } from "react";
import { createPortal } from "react-dom";
import { ArchiveRestore, Trash2, TriangleAlert, X } from "lucide-react";
import { Agent } from "@/types/agents";
import { agentColorBackground } from "@/lib/colors";
import { api } from "@/lib/api/client";

interface ArchivedAgentDialogProps {
	agent: Agent;
	onClose: () => void;
	// Called after the agent leaves the archived list (restored or deleted).
	onRemoved: (agentId: string) => void;
}

export default function ArchivedAgentDialog({
	agent,
	onClose,
	onRemoved,
}: ArchivedAgentDialogProps) {
	const [confirmingDelete, setConfirmingDelete] = useState(false);
	const [busy, setBusy] = useState(false);
	const color = agent.color || "#9E9E9E";

	const handleRestore = async () => {
		setBusy(true);
		try {
			await api.post(`/agents/${agent.id}/restore`);
			onRemoved(agent.id);
			onClose();
		} catch (error) {
			console.error("Error restoring agent:", error);
			alert("Failed to restore agent. Please try again.");
			setBusy(false);
		}
	};

	const handleDelete = async () => {
		setBusy(true);
		try {
			await api.delete(`/agents/${agent.id}/permanent`);
			onRemoved(agent.id);
			onClose();
		} catch (error) {
			console.error("Error deleting agent:", error);
			alert("Failed to delete agent. Please try again.");
			setBusy(false);
		}
	};

	return createPortal(
		<div
			className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(30,45,40,0.2)] backdrop-blur-[4px] animate-in fade-in duration-200"
			onClick={() => !busy && onClose()}
		>
			<div
				className="bg-white dark:bg-card rounded-[28px] p-8 w-[440px] max-w-[90vw] shadow-[0_24px_48px_-12px_rgba(0,0,0,0.12)] animate-in slide-in-from-bottom-4 zoom-in-[0.97] duration-300"
				onClick={(e) => e.stopPropagation()}
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
							Archived
						</div>
					</div>
					<button
						onClick={() => !busy && onClose()}
						className="shrink-0 self-start w-9 h-9 rounded-full bg-[#F5F8F6] dark:bg-white/10 flex items-center justify-center cursor-pointer transition-colors hover:bg-[#EDF4F0] dark:hover:bg-white/15"
					>
						<X className="h-4 w-4 text-[#6B7F76]" />
					</button>
				</div>

				{confirmingDelete ? (
					<>
						<div className="flex items-start gap-2.5 px-4 py-3 mb-6 rounded-xl bg-[#F3E4E6] dark:bg-rose-950/40 text-[#A35462] dark:text-rose-300 text-[13.5px] leading-relaxed">
							<TriangleAlert className="size-4 shrink-0 mt-0.5" />
							<span>
								This permanently deletes the agent, its tool connections, and
								every chat thread that used it. This cannot be undone.
							</span>
						</div>
						<div className="flex gap-2.5">
							<button
								disabled={busy}
								className="flex-1 flex items-center justify-center gap-2 py-3.5 rounded-full border-[1.5px] border-[#E0E8E4] dark:border-white/10 bg-white dark:bg-transparent font-[family-name:var(--font-dm-sans)] text-[14px] font-semibold text-[#1E2D28] dark:text-foreground cursor-pointer transition-all hover:border-[#A3B5AD] disabled:opacity-50"
								onClick={() => setConfirmingDelete(false)}
							>
								Cancel
							</button>
							<button
								disabled={busy}
								className="flex-1 flex items-center justify-center gap-2 py-3.5 rounded-full bg-[#C0455A] font-[family-name:var(--font-dm-sans)] text-[14px] font-semibold text-white cursor-pointer shadow-[0_4px_12px_-2px_rgba(192,69,90,0.3)] transition-all hover:opacity-90 disabled:opacity-50"
								onClick={() => {
									void handleDelete();
								}}
							>
								<Trash2 className="size-[15px]" />
								{busy ? "Deleting..." : "Delete permanently"}
							</button>
						</div>
					</>
				) : (
					<>
						<p className="mb-6 font-[family-name:var(--font-dm-sans)] text-[14px] text-[#6B7F76] dark:text-muted-foreground leading-relaxed">
							Restore this agent to make it available again, or delete it
							permanently to remove it and all of its chat history.
						</p>
						<div className="flex gap-2.5">
							<button
								disabled={busy}
								className="flex-1 flex items-center justify-center gap-2 py-3.5 rounded-full border-[1.5px] border-[#E0E8E4] dark:border-white/10 bg-white dark:bg-transparent font-[family-name:var(--font-dm-sans)] text-[14px] font-semibold text-[#C0455A] cursor-pointer transition-all hover:border-[#C0455A]/40 disabled:opacity-50"
								onClick={() => setConfirmingDelete(true)}
							>
								<Trash2 className="size-[15px]" />
								Delete permanently
							</button>
							<button
								disabled={busy}
								className="flex-1 flex items-center justify-center gap-2 py-3.5 rounded-full bg-[#111111] dark:bg-white font-[family-name:var(--font-dm-sans)] text-[14px] font-semibold text-white dark:text-[#111111] cursor-pointer shadow-[0_4px_12px_-2px_rgba(0,0,0,0.15)] transition-all hover:opacity-90 disabled:opacity-50"
								onClick={() => {
									void handleRestore();
								}}
							>
								<ArchiveRestore className="size-[15px]" />
								{busy ? "Restoring..." : "Restore"}
							</button>
						</div>
					</>
				)}
			</div>
		</div>,
		document.body,
	);
}
