import { cn } from "@/lib/utils";
import type { SkillSourceKind } from "@/types/skills";

/** The host's favicon on a white tile (design 13b server tiles). Works for
 * self-hosted instances too, since it keys on the source's own domain. */
export function SourceHostTile({
	url,
	kind,
	size = 32,
	className,
}: {
	/** Omitted where only the kind is known — the host defaults per kind. */
	url?: string;
	kind: SkillSourceKind;
	size?: 20 | 26 | 32 | 38;
	className?: string;
}) {
	let domain = kind === "gitlab" ? "gitlab.com" : "github.com";
	try {
		if (url) domain = new URL(url).hostname;
	} catch {
		// keep the default domain
	}
	const iconPx = Math.round(size * 0.55);
	return (
		<span
			className={cn(
				"flex shrink-0 items-center justify-center bg-white shadow-[0_2px_6px_rgba(10,25,30,0.14)] dark:bg-white/10",
				size === 20
					? "size-5 rounded-[5px]"
					: size === 26
						? "size-[26px] rounded-[7px]"
						: size === 38
							? "size-[38px] rounded-[10px]"
							: "size-8 rounded-[9px]",
				className,
			)}
		>
			{/* A plain <img>, not next/image: the favicon service is not in
			    `images.remotePatterns`, and the optimizer validates the host
			    whether or not the image is `unoptimized`. Nothing here needs
			    the pipeline — it is a 16px icon from a third party. */}
			{/* eslint-disable-next-line @next/next/no-img-element */}
			<img
				src={`https://www.google.com/s2/favicons?domain=${domain}&sz=64`}
				alt={kind}
				loading="lazy"
				decoding="async"
				width={iconPx}
				height={iconPx}
				className="object-contain"
			/>
		</span>
	);
}
