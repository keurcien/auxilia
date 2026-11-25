"use client";

import { useEffect, useMemo, useState } from "react";
import { Clock, Webhook } from "lucide-react";
import { UsedByList } from "@/components/editor/used-by-list";
import { describeSchedule, parseCronExpression } from "@/lib/triggers/schedule";
import { useTriggersStore } from "@/stores/triggers-store";

/** The triggers that run this agent, among those the viewer can see. */
export default function AgentTriggersUsedBy({ agentId }: { agentId: string }) {
	const triggers = useTriggersStore((state) => state.triggers);
	const isInitialized = useTriggersStore((state) => state.isInitialized);
	const fetchTriggers = useTriggersStore((state) => state.fetchTriggers);
	const [failed, setFailed] = useState(false);

	useEffect(() => {
		fetchTriggers().catch(() => {
			setFailed(true);
		});
	}, [fetchTriggers]);

	const items = useMemo(
		() =>
			triggers
				.filter((trigger) => trigger.agentId === agentId)
				.sort((a, b) => a.name.localeCompare(b.name))
				.map((trigger) => {
					const kind =
						trigger.triggerType === "schedule"
							? describeSchedule(parseCronExpression(trigger.cronExpression))
							: "Webhook";
					const Icon = trigger.triggerType === "schedule" ? Clock : Webhook;
					return {
						id: trigger.id,
						href: `/triggers/${trigger.id}`,
						name: trigger.name,
						leading: (
							<span className="flex size-6 shrink-0 items-center justify-center rounded-[6px] bg-hover dark:bg-white/5">
								<Icon className="size-3.5 text-subtle dark:text-panel-body" />
							</span>
						),
						meta: trigger.isActive ? kind : `${kind} (paused)`,
					};
				}),
		[triggers, agentId],
	);

	return (
		<UsedByList
			className="mt-8"
			loading={!isInitialized && !failed}
			items={items}
			emptyText="No trigger runs this agent yet."
		/>
	);
}
