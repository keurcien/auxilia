import { cn } from "@/lib/utils";

interface EditorSectionProps {
	label: string;
	hint?: string;
	actions?: React.ReactNode;
	className?: string;
	children: React.ReactNode;
}

/**
 * Labeled block of an explicit-save editor: uppercase section label,
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
			<div className="mb-2.5 flex min-h-[30px] items-center justify-between gap-2">
				<label className="font-mono text-[10.5px] font-semibold uppercase tracking-[0.09em] text-subtle dark:text-panel-dim">
					{label}
				</label>
				{actions ??
					(hint && (
						<span className="font-mono text-[11px] text-meta dark:text-panel-dim">
							{hint}
						</span>
					))}
			</div>
			{children}
		</div>
	);
}
