import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { userImageUrl } from "@/lib/api/resources/users";
import { avatarColorStyle } from "@/lib/colors";
import { cn } from "@/lib/utils";

function getInitials(name: string | null | undefined): string {
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
	userId?: string;
	imageRevision?: string | null;
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
 *
 * `alt=""` is deliberate — every call site renders the person's name next to
 * the avatar, so a real alt would just double it up for screen readers. A
 * caller that shows the avatar *alone* inside a control (the collapsed
 * sidebar account button) must label the control itself.
 */
export function UserAvatar({
	name,
	pictureUrl,
	userId,
	imageRevision,
	className,
	fallbackClassName,
}: UserAvatarProps) {
	const uploadedImageUrl =
		userId && imageRevision ? userImageUrl(userId, imageRevision) : null;
	const source = uploadedImageUrl ?? pictureUrl;
	const fallbackStyle = avatarColorStyle(null, name ?? userId ?? "user");
	return (
		<Avatar className={cn("size-8", className)}>
			{source && (
				<AvatarImage
					src={source}
					alt=""
					referrerPolicy="no-referrer"
					className="rounded-full"
				/>
			)}
			<AvatarFallback
				style={fallbackStyle}
				className={cn(
					"text-[10.5px] font-bold",
					fallbackClassName,
				)}
			>
				{getInitials(name)}
			</AvatarFallback>
		</Avatar>
	);
}
