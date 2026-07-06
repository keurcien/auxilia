"use client";

import { useEffect } from "react";
import { AlarmClock, Plus } from "lucide-react";
import TriggerCard from "@/app/(protected)/triggers/components/trigger-card";
import { SageButton } from "@/components/ui/sage-button";
import { useTriggersStore } from "@/stores/triggers-store";
import { useAgentsStore } from "@/stores/agents-store";

interface TriggerListProps {
	view: "active" | "paused";
	onCreate: () => void;
}

export default function TriggerList({ view, onCreate }: TriggerListProps) {
	const triggers = useTriggersStore((state) => state.triggers);
	const isInitialized = useTriggersStore((state) => state.isInitialized);
	const fetchTriggers = useTriggersStore((state) => state.fetchTriggers);
	const deleteTrigger = useTriggersStore((state) => state.deleteTrigger);
	const fetchAgents = useAgentsStore((state) => state.fetchAgents);

	useEffect(() => {
		fetchTriggers().catch(() => {});
		fetchAgents().catch(() => {});
	}, [fetchTriggers, fetchAgents]);

	const visibleTriggers = triggers.filter((trigger) =>
		view === "active" ? trigger.isActive : !trigger.isActive,
	);

	const handleDelete = (id: string) => {
		if (!confirm("Are you sure you want to delete this trigger?")) {
			return;
		}
		deleteTrigger(id).catch((error) => {
			console.error("Error deleting trigger:", error);
			alert("Failed to delete trigger. Please try again.");
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
						Schedule an agent to run on its own, no open session needed.
					</p>
				</div>
				<SageButton
					color="dark"
					onClick={() => {
						onCreate();
					}}
				>
					<Plus className="size-4" />
					New trigger
				</SageButton>
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
					onDelete={handleDelete}
				/>
			))}
		</div>
	);
}
