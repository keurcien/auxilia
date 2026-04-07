import { cn } from "@/lib/utils";
import { agentColorBackground } from "@/lib/colors";

type AvatarSize = "xs" | "sm" | "md" | "lg" | "xl";

function getSizeClass(size: AvatarSize): string {
	switch (size) {
		case "xs": return "w-7 h-7 text-[13px]";
		case "sm": return "w-[34px] h-[34px] text-[15px]";
		case "md": return "w-[42px] h-[42px] text-[20px]";
		case "lg": return "w-[52px] h-[52px] text-[26px]";
		case "xl": return "w-14 h-14 text-[28px]";
	}
}

interface AgentAvatarProps {
	color?: string | null;
	emoji?: string | null;
	size?: AvatarSize;
	className?: string;
}

export function AgentAvatar({
	color,
	emoji,
	size = "md",
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
				"flex items-center justify-center shrink-0 rounded-full",
				getSizeClass(size),
				!color && "bg-[#F0F3F2] dark:bg-white/10",
				className,
			)}
		>
			{emoji || "🤖"}
		</div>
	);
}
