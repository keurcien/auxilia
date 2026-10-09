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
	const summary =
		trigger.triggerType === "schedule"
			? (() => {
					const schedule = parseCronExpression(trigger.cronExpression);
					const scheduleText =
						schedule.kind === "raw"
							? `On the schedule ${schedule.cronExpression}`
							: describeSchedule(schedule).replace(
									/, (?=[^,]*$)/,
									" at ",
								);
					return `${scheduleText}, ${agentName} starts a fresh thread and runs these instructions on its own.`;
				})()
			: `When this webhook receives a POST, ${agentName} starts a fresh thread using these defaults and any supplied overrides.`;

	return (
		<div className="flex flex-col rounded-xl bg-petrol-tint px-6 py-5 dark:bg-white/5">
			<div className="mb-3 flex items-center gap-2">
				<Sparkles className="size-3 text-petrol dark:text-panel-terminal" />
				<span className="text-[10.5px] font-semibold text-petrol dark:text-panel-terminal">
					What this trigger does
				</span>
			</div>
			<p className="text-[18px] font-semibold leading-[1.5] tracking-[-0.015em] text-foreground">
				{summary}
			</p>
		</div>
	);
}
