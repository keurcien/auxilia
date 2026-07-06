import { cn } from "@/lib/utils";

export type StatusPillTone = "green" | "amber" | "neutral";

const TONE_CLASSES: Record<StatusPillTone, { pill: string; dot: string }> = {
	green: {
		pill: "bg-[#EDF4F0] dark:bg-emerald-950/40 text-[#3D8B63] dark:text-emerald-400",
		dot: "bg-[#4CA882]",
	},
	amber: {
		pill: "bg-[#FFF5CC] dark:bg-amber-950/40 text-[#D4A832] dark:text-amber-400",
		dot: "bg-[#FDCB6E]",
	},
	neutral: {
		pill: "bg-[#F0F3F2] dark:bg-white/10 text-[#7D8C84] dark:text-white/60",
		dot: "bg-[#C2CFC8]",
	},
};

interface StatusPillProps {
	tone: StatusPillTone;
	label: string;
	pulse?: boolean;
	className?: string;
}

export function StatusPill({ tone, label, pulse, className }: StatusPillProps) {
	const classes = TONE_CLASSES[tone];
	return (
		<div
			className={cn(
				"inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 font-[family-name:var(--font-dm-sans)] text-[13px] font-semibold transition-all duration-300",
				classes.pill,
				className,
			)}
		>
			<span
				className={cn(
					"block w-[7px] h-[7px] rounded-full transition-all duration-300",
					classes.dot,
					pulse && "animate-pulse-dot",
				)}
			/>
			{label}
		</div>
	);
}
