"use client";

import { useState } from "react";
import { skillImageUrl } from "@/lib/api/resources/skills";
import { avatarColorStyle } from "@/lib/colors";
import { cn } from "@/lib/utils";

type SkillAvatarSize = "xs" | "sm" | "md" | "lg";

function sizeClass(size: SkillAvatarSize): string {
	switch (size) {
		case "xs":
			return "size-6 rounded-[6px] text-[12px]";
		case "sm":
			return "size-8 rounded-[8px] text-[15px]";
		case "md":
			return "size-12 rounded-xl text-[22px]";
		case "lg":
			return "size-16 rounded-[14px] text-[28px]";
	}
}

interface SkillAvatarProps {
	skillId?: string;
	name?: string;
	emoji?: string | null;
	color?: string | null;
	imageRevision?: string | null;
	size?: SkillAvatarSize;
	className?: string;
}

export function SkillAvatar({
	skillId,
	name,
	emoji,
	color,
	imageRevision,
	size = "sm",
	className,
}: SkillAvatarProps) {
	const imageUrl =
		skillId && imageRevision ? skillImageUrl(skillId, imageRevision) : null;
	const [failedUrl, setFailedUrl] = useState<string | null>(null);
	const showsImage = imageUrl !== null && failedUrl !== imageUrl;
	const identityStyle = avatarColorStyle(color, name ?? skillId ?? "skill");
	const initial = name?.trim().charAt(0).toUpperCase() || "S";

	return (
		<span
			aria-hidden="true"
			style={
				!showsImage
					? identityStyle
					: undefined
			}
			className={cn(
				"relative flex shrink-0 items-center justify-center overflow-hidden font-bold uppercase",
				sizeClass(size),
				className,
			)}
			title={name}
		>
			{showsImage ? (
				// Browser-direct request keeps the session cookie.
				// eslint-disable-next-line @next/next/no-img-element
				<img
					src={imageUrl}
					alt=""
					className="size-full object-cover"
					onError={() => {
						setFailedUrl(imageUrl);
					}}
				/>
			) : emoji ? (
				emoji
			) : (
				initial
			)}
		</span>
	);
}
