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
	name,
	size = 32,
	className,
}: ServerIconTileProps) {
	const { tileClass, iconPx } = tileFor(size);
	return (
		<span
			className={cn(
				"flex shrink-0 items-center justify-center bg-white shadow-[0_2px_6px_rgba(10,25,30,0.14)] dark:bg-white/10",
				tileClass,
				className,
			)}
		>
			<Image
				unoptimized
				src={iconUrl ?? DEFAULT_ICON}
				alt={name}
				width={iconPx}
				height={iconPx}
				className="object-contain"
			/>
		</span>
	);
}
