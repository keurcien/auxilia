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
		<div className="flex flex-col rounded-2xl border border-[#E4F0E9] dark:border-emerald-900/30 bg-[#F5FAF7] dark:bg-emerald-950/20 px-6 py-5">
			<div className="flex items-center gap-2 mb-3">
				<span className="flex items-center justify-center rounded-md bg-[#E1F0E8] dark:bg-emerald-900/40 p-1">
					<Sparkles className="size-3 text-[#3D8B63] dark:text-emerald-400" />
				</span>
				<span className="font-[family-name:var(--font-dm-sans)] text-[10.5px] font-bold uppercase tracking-[0.12em] text-[#6E8E7D] dark:text-emerald-300/70">
					What this trigger does
				</span>
			</div>
			<p className="font-[family-name:var(--font-jakarta-sans)] text-[19px] font-semibold leading-[1.45] tracking-[-0.015em] text-[#26352F] dark:text-emerald-50">
				{scheduleText}, {agentName} starts a fresh thread and runs these
				instructions on its own.
			</p>
		</div>
	);
}
