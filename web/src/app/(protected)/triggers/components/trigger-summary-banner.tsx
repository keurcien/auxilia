import { Sparkles } from "lucide-react";
import { Trigger } from "@/types/triggers";
import { describeSchedule, parseCronExpression } from "@/lib/triggers/schedule";

interface TriggerSummaryBannerProps {
	trigger: Trigger;
	agentName: string;
}

/** Plain-language recap of the trigger — a deterministic template, no LLM. */
export default function TriggerSummaryBanner({
	trigger,
	agentName,
}: TriggerSummaryBannerProps) {
	const schedule = parseCronExpression(trigger.cronExpression);
	const scheduleText =
		schedule.kind === "raw"
			? `On the schedule ${schedule.cronExpression}`
			: describeSchedule(schedule).replace(" · ", " at ");

	return (
		<div className="flex flex-col rounded-xl bg-petrol-tint px-6 py-5 dark:bg-white/5">
			<div className="mb-3 flex items-center gap-2">
				<Sparkles className="size-3 text-petrol dark:text-panel-terminal" />
				<span className="font-mono text-[10.5px] font-semibold uppercase tracking-[0.09em] text-petrol dark:text-panel-terminal">
					What this trigger does
				</span>
			</div>
			<p className="text-[18px] font-semibold leading-[1.5] tracking-[-0.015em] text-foreground">
				{scheduleText}, {agentName} starts a fresh thread and runs these
				instructions on its own.
			</p>
		</div>
	);
}
