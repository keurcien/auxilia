"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { avatarColorStyle } from "@/lib/colors";
import { agentImageUrl } from "@/lib/api/resources/agents";

type AvatarSize = "2xs" | "xs" | "sm" | "md" | "lg" | "xl";

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

interface AgentAvatarProps {
	color?: string | null;
	emoji?: string | null;
	name?: string | null;
	agentId?: string | null;
	imageRevision?: string | null;
	size?: AvatarSize;
	className?: string;
}

export function AgentAvatar({
	color,
	emoji,
	name,
	agentId,
	imageRevision,
	size = "md",
	className,
}: AgentAvatarProps) {
	const imageUrl =
		agentId && imageRevision ? agentImageUrl(agentId, imageRevision) : null;
	const [failedUrl, setFailedUrl] = useState<string | null>(null);
	const imageFailed = imageUrl !== null && failedUrl === imageUrl;
	const showsImage = imageUrl !== null && !imageFailed;
	const identityStyle = avatarColorStyle(color, name ?? agentId ?? "agent");
	const initial = name?.trim().charAt(0).toUpperCase();

	return (
		<div
			style={
				!showsImage
					? identityStyle
					: undefined
			}
			className={cn(
				"flex shrink-0 items-center justify-center overflow-hidden rounded-full font-bold uppercase",
				getSizeClass(size),
				className,
			)}
		>
			{showsImage ? (
				// Browser-direct request keeps the session cookie; Next's optimizer does not.
				// eslint-disable-next-line @next/next/no-img-element
				<img
					src={imageUrl}
					alt=""
					className="size-full rounded-full object-cover"
					onError={() => {
						setFailedUrl(imageUrl);
					}}
				/>
			) : (
				emoji || initial || "🤖"
			)}
		</div>
	);
}
