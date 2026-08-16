import { cn } from "@/lib/utils";
import { agentColorBackground } from "@/lib/colors";

type AvatarSize = "2xs" | "xs" | "sm" | "md" | "lg" | "xl";

/**
 * Petrol Mono: emoji on a pastel background. Default is round (999px) —
 * the chat header and small subagent chips ("22px emoji circles on their
 * pastels", design 7a). Pass shape="tile" (radius ≈ size/4) for agent
 * identity tiles in lists and editors.
 */
type AvatarShape = "tile" | "round";

function getSizeClass(size: AvatarSize): string {
	switch (size) {
		case "2xs": return "w-[22px] h-[22px] text-[12px]";
		case "xs": return "w-7 h-7 text-[13px]";
		case "sm": return "w-[34px] h-[34px] text-[15px]";
		case "md": return "w-[42px] h-[42px] text-[20px]";
		case "lg": return "w-[52px] h-[52px] text-[26px]";
		case "xl": return "w-14 h-14 text-[28px]";
	}
}

function getTileRadiusClass(size: AvatarSize): string {
	switch (size) {
		case "2xs": return "rounded-[6px]";
		case "xs": return "rounded-[7px]";
		case "sm": return "rounded-lg";
		case "md": return "rounded-[10px]";
		case "lg": return "rounded-xl";
		case "xl": return "rounded-[14px]";
	}
}

interface AgentAvatarProps {
	color?: string | null;
	emoji?: string | null;
	size?: AvatarSize;
	shape?: AvatarShape;
	className?: string;
}

export function AgentAvatar({
	color,
	emoji,
	size = "md",
	shape = "round",
	className,
}: AgentAvatarProps) {
	return (
		<div
			style={
				color
					? {
							background: agentColorBackground(color),
							border: `1.5px solid ${color}18`,
						}
					: undefined
			}
			className={cn(
				"flex items-center justify-center shrink-0",
				shape === "round" ? "rounded-full" : getTileRadiusClass(size),
				getSizeClass(size),
				!color && "bg-hover dark:bg-white/10",
				className,
			)}
		>
			{emoji || "🤖"}
		</div>
	);
}
