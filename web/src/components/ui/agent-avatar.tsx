import { cn } from "@/lib/utils";
import { agentColorBackground } from "@/lib/colors";

const sizeClasses = {
	xs: "w-7 h-7 text-[13px]",
	sm: "w-[34px] h-[34px] text-[15px]",
	md: "w-[42px] h-[42px] text-[20px]",
	lg: "w-[52px] h-[52px] text-[26px]",
	xl: "w-14 h-14 text-[28px]",
};

interface AgentAvatarProps {
	color?: string | null;
	emoji?: string | null;
	size?: keyof typeof sizeClasses;
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
				sizeClasses[size],
				!color && "bg-[#F0F3F2] dark:bg-white/10",
				className,
			)}
		>
			{emoji || "🤖"}
		</div>
	);
}
