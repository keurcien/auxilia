import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { cn } from "@/lib/utils";

export function getInitials(name: string | null | undefined): string {
	if (!name?.trim()) return "?";
	const parts = name.trim().split(/\s+/);
	if (parts.length >= 2) {
		return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
	}
	return name.trim().substring(0, 2).toUpperCase();
}

interface UserAvatarProps {
	name: string | null | undefined;
	pictureUrl: string | null | undefined;
	/** Sizing/shape for the avatar root (e.g. `size-7`). */
	className?: string;
	/** Overrides the initials chip styling (colors, font size). */
	fallbackClassName?: string;
}

/**
 * A person's profile picture, falling back to their initials.
 *
 * `referrerPolicy="no-referrer"` is required: Google serves the OAuth picture
 * from lh3.googleusercontent.com and 403s requests that carry a referrer.
 */
export function UserAvatar({
	name,
	pictureUrl,
	className,
	fallbackClassName,
}: UserAvatarProps) {
	return (
		<Avatar className={cn("size-8", className)}>
			{pictureUrl && (
				<AvatarImage src={pictureUrl} alt="" referrerPolicy="no-referrer" />
			)}
			<AvatarFallback
				className={cn(
					"bg-ink text-[10.5px] font-bold text-white dark:bg-white/15",
					fallbackClassName,
				)}
			>
				{getInitials(name)}
			</AvatarFallback>
		</Avatar>
	);
}
