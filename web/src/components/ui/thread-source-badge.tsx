import Image from "next/image";
import { AlarmClock, Globe, Plug } from "lucide-react";
import type { ThreadSource } from "@/types/threads";

const SLACK_ICON_SRC =
	"https://storage.googleapis.com/choose-assets/slack.png";

function getLabel(source: ThreadSource): string {
	switch (source) {
		case "web":
			return "In-app";
		case "slack":
			return "Slack";
		case "api":
			return "External";
		case "trigger":
			return "Trigger";
	}
}

interface ThreadSourceBadgeProps {
	source: ThreadSource;
	withLabel?: boolean;
	className?: string;
}

export function ThreadSourceBadge({
	source,
	withLabel = true,
	className = "",
}: ThreadSourceBadgeProps) {
	const label = getLabel(source);
	const icon =
		source === "slack" ? (
			<Image
				src={SLACK_ICON_SRC}
				alt="Slack"
				height={14}
				width={14}
				className="h-3.5 w-3.5 shrink-0"
			/>
		) : source === "web" ? (
			<Globe className="h-3.5 w-3.5 shrink-0 text-[#A3B5AD] dark:text-muted-foreground" />
		) : source === "trigger" ? (
			<AlarmClock className="h-3.5 w-3.5 shrink-0 text-[#3D8B63] dark:text-emerald-400" />
		) : (
			<Plug className="h-3.5 w-3.5 shrink-0 text-[#A3B5AD] dark:text-muted-foreground" />
		);
	return (
		<span
			className={`inline-flex items-center gap-1.5 text-[12px] font-medium text-[#6E7C76] dark:text-muted-foreground ${className}`}
			title={`Thread initiated from ${label}`}
		>
			{icon}
			{withLabel && <span>{label}</span>}
		</span>
	);
}
