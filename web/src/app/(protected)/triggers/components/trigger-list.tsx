"use client";

import { useEffect } from "react";
import { AlarmClock, Plus } from "lucide-react";
import { toast } from "sonner";
import TriggerCard from "@/app/(protected)/triggers/components/trigger-card";
import { useConfirmDialog } from "@/components/providers/dialog-provider";
import { useTriggersStore } from "@/stores/triggers-store";
import { useAgentsStore } from "@/stores/agents-store";

interface TriggerListProps {
	view: "active" | "paused";
	onCreate: () => void;
	canCreate: boolean;
}

export default function TriggerList({ view, onCreate, canCreate }: TriggerListProps) {
	const triggers = useTriggersStore((state) => state.triggers);
	const isInitialized = useTriggersStore((state) => state.isInitialized);
	const fetchTriggers = useTriggersStore((state) => state.fetchTriggers);
	const deleteTrigger = useTriggersStore((state) => state.deleteTrigger);
	const fetchAgents = useAgentsStore((state) => state.fetchAgents);
	const confirmDialog = useConfirmDialog();

	useEffect(() => {
		fetchTriggers().catch(() => {});
		fetchAgents().catch(() => {});
	}, [fetchTriggers, fetchAgents]);

	const visibleTriggers = triggers.filter((trigger) =>
		view === "active" ? trigger.isActive : !trigger.isActive,
	);

	const handleDelete = async (id: string) => {
		if (
			!(await confirmDialog({
				title: "Delete this trigger?",
				description:
					"Its configuration will be removed permanently. Existing run history is unaffected.",
				confirmLabel: "Delete trigger",
				destructive: true,
			}))
		) {
			return;
		}
		deleteTrigger(id).catch((error) => {
			console.error("Error deleting trigger:", error);
			toast.error("Failed to delete trigger. Please try again.");
		});
	};

	if (isInitialized && triggers.length === 0) {
		return (
			<div className="flex flex-col items-center justify-center gap-4 rounded-2xl border border-dashed border-[#D7E0DB] dark:border-white/10 py-20">
				<div className="flex items-center justify-center size-12 rounded-2xl bg-[#EDF4F0] dark:bg-emerald-950/40">
					<AlarmClock className="size-6 text-[#3D8B63] dark:text-emerald-400" />
				</div>
				<div className="text-center">
					<p className="font-[family-name:var(--font-jakarta-sans)] text-[16px] font-bold text-[#1E2D28] dark:text-foreground">
						No triggers yet
					</p>
					<p className="mt-1 font-[family-name:var(--font-dm-sans)] text-[13.5px] text-[#6B7F76] dark:text-muted-foreground">
						Run an agent from a schedule or an external webhook.
					</p>
				</div>
				{canCreate && (
					<button
						type="button"
						onClick={() => {
							onCreate();
						}}
						className="inline-flex cursor-pointer items-center gap-1.5 rounded-[7px] bg-primary px-3.5 py-[7px] text-[12.5px] font-semibold text-primary-foreground transition-opacity hover:opacity-90"
					>
						<Plus className="size-4" />
						New trigger
					</button>
				)}
			</div>
		);
	}

	if (visibleTriggers.length === 0) {
		return (
			<div className="py-16 text-center font-[family-name:var(--font-dm-sans)] text-[13.5px] text-[#A3B5AD] dark:text-muted-foreground">
				{view === "active" ? "No active triggers." : "No paused triggers."}
			</div>
		);
	}

	return (
		<div className="grid gap-4 md:grid-cols-2">
			{visibleTriggers.map((trigger) => (
				<TriggerCard
					key={trigger.id}
					trigger={trigger}
					onDelete={(id) => {
						void handleDelete(id);
					}}
				/>
			))}
		</div>
	);
}
