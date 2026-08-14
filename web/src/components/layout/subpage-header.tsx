import Link from "next/link";
import { Fragment } from "react";

export interface BreadcrumbSegment {
	label: string;
	href?: string;
}

/**
 * 52px top bar for workspace subpages (MCP servers add/custom/detail,
 * trigger editor/detail): mono breadcrumb trail on the left, an optional
 * status badge (e.g. UNSAVED), action buttons on the right. Mirrors the
 * agent editor's header bar.
 */
export function SubpageHeader({
	trail,
	badge,
	children,
}: {
	trail: BreadcrumbSegment[];
	badge?: React.ReactNode;
	children?: React.ReactNode;
}) {
	return (
		<header className="flex h-[52px] shrink-0 items-center gap-3 border-b border-border pl-14 pr-4 md:px-7">
			<span className="min-w-0 truncate font-mono text-[11.5px] text-meta dark:text-panel-dim">
				{trail.map((segment, i) => {
					const isLast = i === trail.length - 1;
					return (
						<Fragment key={`${segment.label}-${i}`}>
							{i > 0 && (
								<span className="text-ghost dark:text-panel-dim"> / </span>
							)}
							{segment.href ? (
								<Link
									href={segment.href}
									className="transition-colors hover:text-foreground"
								>
									{segment.label}
								</Link>
							) : (
								<span
									className={
										isLast ? "font-medium text-foreground" : undefined
									}
								>
									{segment.label}
								</span>
							)}
						</Fragment>
					);
				})}
			</span>
			{badge}
			<div className="ml-auto flex shrink-0 items-center gap-2">{children}</div>
		</header>
	);
}

/** Amber UNSAVED chip for explicit-save editors (matches the agent editor). */
export function UnsavedBadge() {
	return (
		<span className="rounded-[4px] bg-warning-bg px-2 py-0.5 font-mono text-[10px] font-semibold tracking-[0.05em] text-warning">
			UNSAVED
		</span>
	);
}

/** Outline header button (Cancel, Edit server…). Teal text via `accent`. */
export function HeaderButton({
	accent = false,
	className,
	children,
	...props
}: React.ComponentProps<"button"> & { accent?: boolean }) {
	return (
		<button
			type="button"
			className={`flex cursor-pointer items-center gap-1.5 rounded-[7px] border border-input bg-card px-4 py-2 text-[13px] font-semibold transition-colors hover:border-border-hover disabled:cursor-not-allowed disabled:opacity-50 ${
				accent ? "text-petrol" : "text-foreground"
			} ${className ?? ""}`}
			{...props}
		>
			{children}
		</button>
	);
}

/** Filled petrol primary header button (Save changes, Add server…). */
export function HeaderPrimaryButton({
	className,
	children,
	...props
}: React.ComponentProps<"button">) {
	return (
		<button
			type="button"
			className={`cursor-pointer rounded-[7px] bg-petrol px-[18px] py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50 ${className ?? ""}`}
			{...props}
		>
			{children}
		</button>
	);
}
