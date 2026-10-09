"use client";

import { useState } from "react";
import { Building2 } from "lucide-react";

import { workspaceImageUrl } from "@/lib/api/resources/workspaces";
import { avatarColorStyle } from "@/lib/colors";
import { cn } from "@/lib/utils";

type WorkspaceAvatarSize = "xs" | "sm" | "md" | "lg";

function sizeClass(size: WorkspaceAvatarSize): string {
	switch (size) {
		case "xs":
			return "size-6 rounded-[6px] text-[11px]";
		case "sm":
			return "size-8 rounded-[8px] text-[14px]";
		case "md":
			return "size-12 rounded-[11px] text-[21px]";
		case "lg":
			return "size-16 rounded-[14px] text-[28px]";
	}
}

interface WorkspaceAvatarProps {
	workspaceId?: string | null;
	name?: string | null;
	emoji?: string | null;
	color?: string | null;
	imageRevision?: string | null;
	size?: WorkspaceAvatarSize;
	className?: string;
}

export function WorkspaceAvatar({
	workspaceId,
	name,
	emoji,
	color,
	imageRevision,
	size = "sm",
	className,
}: WorkspaceAvatarProps) {
	const imageUrl =
		workspaceId && imageRevision
			? workspaceImageUrl(workspaceId, imageRevision)
			: null;
	const [failedUrl, setFailedUrl] = useState<string | null>(null);
	const showsImage = imageUrl !== null && failedUrl !== imageUrl;
	const initial = name?.trim().charAt(0).toUpperCase();
	const identityStyle = avatarColorStyle(
		color,
		name ?? workspaceId ?? "workspace",
	);

	return (
		<span
			aria-hidden="true"
			style={
				!showsImage
					? identityStyle
					: undefined
			}
			className={cn(
				"flex shrink-0 items-center justify-center overflow-hidden font-bold uppercase text-label",
				sizeClass(size),
				className,
			)}
		>
			{showsImage ? (
				// Browser-direct request keeps the session cookie; Next's optimizer does not.
				// eslint-disable-next-line @next/next/no-img-element
				<img
					src={imageUrl}
					alt=""
					className="size-full object-cover"
					onError={() => {
						setFailedUrl(imageUrl);
					}}
				/>
			) : (
				emoji || initial || <Building2 className="size-1/2" />
			)}
		</span>
	);
}
