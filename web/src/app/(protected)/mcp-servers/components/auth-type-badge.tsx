import { MCPAuthType } from "@/types/mcp-servers";
import { cn } from "@/lib/utils";

const BADGES: Record<MCPAuthType, { label: string; className: string }> = {
	oauth2: {
		label: "OAUTH 2.0",
		className:
			"bg-[#E7F0FA] text-[#2E6FA8] dark:bg-sky-950 dark:text-sky-300",
	},
	api_key: {
		label: "API KEY",
		className:
			"bg-neutral-bg text-subtle dark:bg-white/10 dark:text-panel-body",
	},
	none: {
		label: "OPEN",
		className:
			"bg-neutral-bg text-subtle dark:bg-white/10 dark:text-panel-body",
	},
};

/** Mono-caps auth chip: OAUTH 2.0 (blue) · API KEY / OPEN (neutral). */
export function AuthTypeBadge({
	authType,
	className,
}: {
	authType: MCPAuthType;
	className?: string;
}) {
	const badge = BADGES[authType];
	return (
		<span
			className={cn(
				"inline-flex shrink-0 items-center rounded-[4px] px-2 py-[3px] font-mono text-[9.5px] font-semibold tracking-[0.05em]",
				badge.className,
				className,
			)}
		>
			{badge.label}
		</span>
	);
}
