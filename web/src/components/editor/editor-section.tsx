import { cn } from "@/lib/utils";

interface EditorSectionProps {
	label: string;
	hint?: string;
	actions?: React.ReactNode;
	className?: string;
	children: React.ReactNode;
}

/**
 * Labeled block of an explicit-save editor:  section label,
 * optional right-aligned hint or actions, then the field content.
 */
export function EditorSection({
	label,
	hint,
	actions,
	className,
	children,
}: EditorSectionProps) {
	return (
		<div className={cn("flex flex-col", className)}>
			<div className="mb-1.5 flex items-center justify-between gap-2">
				<label className="text-[11px] font-semibold text-label dark:text-muted-foreground">
					{label}
				</label>
				{actions ??
					(hint && (
						<span className="text-[11px] text-meta dark:text-panel-dim">
							{hint}
						</span>
					))}
			</div>
			{children}
		</div>
	);
}
