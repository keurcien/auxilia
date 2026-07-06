import { cn } from "@/lib/utils";

interface EditorHeaderProps {
	icon: React.ReactNode;
	/** Tile background/foreground, e.g. "bg-[#FFF5CC] text-[#9A7B12]". */
	iconClassName?: string;
	title: string;
	/** When set, the title renders as a borderless inline input. */
	onTitleChange?: (title: string) => void;
	titlePlaceholder?: string;
	subtitle?: React.ReactNode;
	actions?: React.ReactNode;
	className?: string;
}

/**
 * Top bar of an explicit-save editor page: icon tile, page title
 * (optionally editable inline), a subtitle row (status pill, next-run
 * line…), and a right-aligned actions slot.
 */
export function EditorHeader({
	icon,
	iconClassName,
	title,
	onTitleChange,
	titlePlaceholder,
	subtitle,
	actions,
	className,
}: EditorHeaderProps) {
	const titleClassName =
		"font-[family-name:var(--font-jakarta-sans)] text-[22px] font-bold text-[#1E2D28] dark:text-foreground leading-tight tracking-[-0.025em] truncate w-full";

	return (
		<div
			className={cn(
				"flex flex-col md:flex-row md:items-center gap-3 md:gap-4",
				className,
			)}
		>
			<div className="flex items-center gap-4 flex-1 min-w-0">
				<div
					className={cn(
						"flex items-center justify-center shrink-0 size-[46px] rounded-[13px]",
						iconClassName,
					)}
				>
					{icon}
				</div>
				<div className="flex flex-col overflow-hidden flex-1">
					{onTitleChange ? (
						<input
							type="text"
							value={title}
							onChange={(e) => {
								onTitleChange(e.target.value);
							}}
							placeholder={titlePlaceholder}
							className={cn(
								titleClassName,
								"bg-transparent border-none focus:outline-none focus:ring-0 p-0 placeholder:text-[#A3B5AD] dark:placeholder:text-white/30",
							)}
						/>
					) : (
						<h1 className={titleClassName}>
							{title || titlePlaceholder}
						</h1>
					)}
					{subtitle && (
						<div className="flex items-center gap-2.5 mt-1">{subtitle}</div>
					)}
				</div>
			</div>
			{actions && (
				<div className="flex items-center gap-2.5 shrink-0">{actions}</div>
			)}
		</div>
	);
}
