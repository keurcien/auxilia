"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import TriggerList from "@/app/(protected)/triggers/components/trigger-list";
import { UnderlineTabs } from "@/components/ui/underline-tabs";
import {
	WorkspacePage,
	WorkspaceTopBarButton,
} from "@/components/layout/workspace-page";
import { useTriggersStore } from "@/stores/triggers-store";

export default function TriggersPage() {
	const router = useRouter();
	const triggers = useTriggersStore((state) => state.triggers);
	const [view, setView] = useState<"active" | "paused">("active");

	const activeCount = triggers.filter((trigger) => trigger.isActive).length;
	const pausedCount = triggers.length - activeCount;

	const handleCreate = () => {
		router.push("/triggers/new");
	};

	return (
		<WorkspacePage
			slug="triggers"
			title="Triggers"
			intro="Your agents working in the background, on the schedule you choose."
			actions={
				<WorkspaceTopBarButton
					onClick={() => {
						handleCreate();
					}}
				>
					<Plus className="size-3.5" />
					New trigger
				</WorkspaceTopBarButton>
			}
			headerRight={
				<UnderlineTabs
					tabs={[
						{ key: "active", label: "Active", count: activeCount },
						{ key: "paused", label: "Paused", count: pausedCount },
					]}
					value={view}
					onChange={setView}
				/>
			}
		>
			<TriggerList view={view} onCreate={handleCreate} />
		</WorkspacePage>
	);
}
