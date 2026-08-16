"use client";

import { useState } from "react";
import { TriangleAlert } from "lucide-react";
import { Agent } from "@/types/agents";
import { api } from "@/lib/api/client";
import AgentDialogShell from "@/app/(protected)/agents/components/agent-dialog-shell";

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

	return (
		<AgentDialogShell
			agent={agent}
			subtitle="Archived"
			onClose={onClose}
			closeDisabled={busy}
		>
			{confirmingDelete ? (
				<>
					<div className="mb-5 flex items-start gap-2.5 rounded-[10px] bg-[#FBEFED] px-4 py-3 text-[13px] leading-[1.55] text-[#B04A3A] dark:bg-[#B04A3A]/10">
						<TriangleAlert className="mt-0.5 size-4 shrink-0" />
						<span>
							This permanently deletes the agent, its tool connections, and
							every chat thread that used it. This cannot be undone.
						</span>
					</div>
					<div className="flex justify-end gap-2">
						<button
							disabled={busy}
							className="cursor-pointer rounded-[7px] border border-input px-[18px] py-2 text-[13px] font-semibold text-ink transition-colors hover:border-border-hover disabled:cursor-not-allowed disabled:opacity-50 dark:text-panel-button dark:hover:border-white/30"
							onClick={() => {
								setConfirmingDelete(false);
							}}
						>
							Cancel
						</button>
						<button
							disabled={busy}
							className="cursor-pointer rounded-[7px] bg-[#B04A3A] px-[18px] py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
							onClick={() => {
								void handleDelete();
							}}
						>
							{busy ? "Deleting…" : "Delete permanently"}
						</button>
					</div>
				</>
			) : (
				<>
					<p className="mb-5 text-[13.5px] leading-[1.6] text-body dark:text-panel-body">
						Restore this agent to make it available again, or delete it
						permanently to remove it and all of its chat history.
					</p>
					<div className="flex justify-end gap-2">
						<button
							disabled={busy}
							className="cursor-pointer rounded-[7px] border border-input px-[18px] py-2 text-[13px] font-semibold text-[#B04A3A] transition-colors hover:bg-[#FBEFED] disabled:cursor-not-allowed disabled:opacity-50 dark:hover:bg-[#B04A3A]/10"
							onClick={() => {
								setConfirmingDelete(true);
							}}
						>
							Delete permanently
						</button>
						<button
							disabled={busy}
							className="cursor-pointer rounded-[7px] bg-petrol px-[18px] py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
							onClick={() => {
								void handleRestore();
							}}
						>
							{busy ? "Restoring…" : "Restore"}
						</button>
					</div>
				</>
			)}
		</AgentDialogShell>
	);
}
