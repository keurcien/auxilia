import Image from "next/image";
import { cn } from "@/lib/utils";
import { DEFAULT_ICON } from "../lib/constants";

interface ServerIconTileProps {
	iconUrl?: string | null;
	name: string;
	/** Outer tile size in px (icon scales to ~55%). */
	size?: 32 | 38 | 52;
	className?: string;
}

const TILE_CLASSES: Record<number, string> = {
	32: "size-8 rounded-[9px]",
	38: "size-[38px] rounded-[10px]",
	52: "size-[52px] rounded-[14px] shadow-[0_2px_8px_rgba(10,25,30,0.16)]",
};

const ICON_SIZES: Record<number, number> = { 32: 17, 38: 20, 52: 28 };

/** White logo tile with the design system's soft shadow. */
export function ServerIconTile({
	iconUrl,
	name,
	size = 32,
	className,
}: ServerIconTileProps) {
	return (
		<span
			className={cn(
				"flex shrink-0 items-center justify-center bg-white shadow-[0_2px_6px_rgba(10,25,30,0.14)] dark:bg-white/10",
				TILE_CLASSES[size],
				className,
			)}
		>
			<Image
				unoptimized
				src={iconUrl ?? DEFAULT_ICON}
				alt={name}
				width={ICON_SIZES[size]}
				height={ICON_SIZES[size]}
				className="object-contain"
			/>
		</span>
	);
}
