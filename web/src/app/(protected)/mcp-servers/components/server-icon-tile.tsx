"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { mcpServerImageUrl } from "@/lib/api/resources/mcp-servers";
import { avatarColorStyle } from "@/lib/colors";

interface ServerIconTileProps {
	iconUrl?: string | null;
	serverId?: string | null;
	imageRevision?: string | null;
	name: string;
	/** Outer tile size in px (icon scales to ~55%). */
	size?: 32 | 38 | 52;
	className?: string;
}

// Exhaustive switch (not a keyed lookup) so static analysis can verify the
// access — the size union guarantees every case is covered.
function tileFor(size: 32 | 38 | 52): { tileClass: string; iconPx: number } {
	switch (size) {
		case 32:
			return { tileClass: "size-8 rounded-[9px]", iconPx: 17 };
		case 38:
			return { tileClass: "size-[38px] rounded-[10px]", iconPx: 20 };
		case 52:
			return {
				tileClass:
					"size-[52px] rounded-[14px] shadow-[0_2px_8px_rgba(10,25,30,0.16)]",
				iconPx: 28,
			};
	}
}

/** White logo tile with the design system's soft shadow. */
export function ServerIconTile({
	iconUrl,
	serverId,
	imageRevision,
	name,
	size = 32,
	className,
}: ServerIconTileProps) {
	const { tileClass, iconPx } = tileFor(size);
	const uploadedUrl =
		serverId && imageRevision
			? mcpServerImageUrl(serverId, imageRevision)
			: null;
	const source = uploadedUrl ?? iconUrl ?? null;
	const [failedSource, setFailedSource] = useState<string | null>(null);
	const showsImage = source !== null && failedSource !== source;
	const showsUploadedImage = showsImage && source === uploadedUrl;
	const fallbackStyle = avatarColorStyle(null, name);
	const initial = name.trim().charAt(0).toUpperCase() || "M";

	return (
		<span
			style={showsImage ? undefined : fallbackStyle}
			className={cn(
				"flex shrink-0 items-center justify-center font-bold uppercase shadow-[0_2px_6px_rgba(10,25,30,0.14)]",
				showsUploadedImage
					? "overflow-hidden"
					: showsImage && "bg-white dark:bg-white/10",
				tileClass,
				className,
			)}
		>
			{/* Browser-direct requests preserve auth for uploaded images and allow
			    arbitrary external hosts without Next optimizer rules. */}
			{showsImage ? (
				// eslint-disable-next-line @next/next/no-img-element
				<img
					src={source}
					alt={name}
					width={showsUploadedImage ? size : iconPx}
					height={showsUploadedImage ? size : iconPx}
					className={
						showsUploadedImage ? "size-full object-cover" : "object-contain"
					}
					onError={() => {
						setFailedSource(source);
					}}
				/>
			) : (
				initial
			)}
		</span>
	);
}
