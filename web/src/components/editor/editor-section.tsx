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
			<div className="flex items-center justify-between min-h-[34px] mb-2.5 gap-2">
				<label className="font-[family-name:var(--font-dm-sans)] text-[10.5px] font-bold text-[#94a59d] dark:text-muted-foreground uppercase tracking-[0.12em]">
					{label}
				</label>
				{actions ??
					(hint && (
						<span className="font-[family-name:var(--font-dm-sans)] text-[12px] font-medium text-[#A9B7B0] dark:text-muted-foreground">
							{hint}
						</span>
					))}
			</div>
			{children}
		</div>
	);
}
