import { MCPAuthType } from "@/types/mcp-servers";
import { cn } from "@/lib/utils";

// Exhaustive switch (not a keyed lookup) so static analysis can verify the
// access — the union type guarantees every case is covered.
function badgeFor(authType: MCPAuthType): { label: string; className: string } {
	switch (authType) {
		case "oauth2":
			return {
				label: "OAUTH 2.0",
				className:
					"bg-[#E7F0FA] text-[#2E6FA8] dark:bg-sky-950 dark:text-sky-300",
			};
		case "api_key":
			return {
				label: "API KEY",
				className:
					"bg-neutral-bg text-subtle dark:bg-white/10 dark:text-panel-body",
			};
		case "none":
			return {
				label: "OPEN",
				className:
					"bg-neutral-bg text-subtle dark:bg-white/10 dark:text-panel-body",
			};
	}
}

/** Mono-caps auth chip: OAUTH 2.0 (blue) · API KEY / OPEN (neutral). */
export function AuthTypeBadge({
	authType,
	className,
}: {
	authType: MCPAuthType;
	className?: string;
}) {
	const badge = badgeFor(authType);
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
