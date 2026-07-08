"use client";

import type { CSSProperties, ReactNode } from "react";
import Link from "next/link";
import { ChevronLeft, ChevronRight } from "lucide-react";

export interface DataTableColumn<T> {
	key: string;
	header: ReactNode;
	/** Grid track for this column on md+ screens (e.g. "1fr", "120px"). */
	width?: string;
	/** Grid track below md; defaults to `width`. Ignored when `hideBelowMd`. */
	mobileWidth?: string;
	/** Render the column only on md+ screens. */
	hideBelowMd?: boolean;
	align?: "left" | "right";
	cell: (row: T) => ReactNode;
}

export interface DataTablePagination {
	total: number;
	limit: number;
	offset: number;
	onOffsetChange: (offset: number) => void;
}

interface DataTableProps<T> {
	columns: DataTableColumn<T>[];
	rows: T[];
	rowKey: (row: T) => string;
	isLoading?: boolean;
	emptyMessage?: ReactNode;
	/** When set, each row renders as a link to this href. */
	getRowHref?: (row: T) => string;
	pagination?: DataTablePagination;
	className?: string;
}

const HEADER_LABEL_CLASS =
	"text-[10px] font-semibold uppercase tracking-[0.1em] text-[#94a59d]";
const ROW_CLASS =
	"group border-b border-[#edf2ef] py-[11px] transition-colors duration-[110ms] last:border-b-0 hover:bg-[#eff4f1] dark:border-white/5 dark:hover:bg-white/5";

function cellClass(column: Pick<DataTableColumn<never>, "hideBelowMd" | "align">): string {
	return [
		"min-w-0",
		column.hideBelowMd ? "hidden md:block" : "",
		column.align === "right" ? "text-right" : "",
	]
		.filter(Boolean)
		.join(" ");
}

function PaginationFooter({
	total,
	limit,
	offset,
	onOffsetChange,
}: DataTablePagination) {
	const start = total === 0 ? 0 : offset + 1;
	const end = Math.min(offset + limit, total);
	const canPrev = offset > 0;
	const canNext = end < total;
	const pagerButtonClass =
		"flex size-7 items-center justify-center rounded-[7px] border border-[#e1ebe6] text-[#5f7068] cursor-pointer transition-colors hover:bg-[#f8faf9] disabled:cursor-default disabled:opacity-40 disabled:hover:bg-transparent dark:border-white/10 dark:text-muted-foreground dark:hover:bg-white/5";
	return (
		<div className="flex items-center justify-between border-t border-[#edf2ef] px-[18px] py-[9px] dark:border-white/5">
			<span className="font-[family-name:var(--font-dm-sans)] text-[11.5px] font-medium text-[#94a59d] dark:text-muted-foreground">
				{start}–{end} of {total}
			</span>
			<div className="flex items-center gap-1.5">
				<button
					type="button"
					aria-label="Previous page"
					disabled={!canPrev}
					className={pagerButtonClass}
					onClick={() => {
						onOffsetChange(Math.max(0, offset - limit));
					}}
				>
					<ChevronLeft className="size-4" />
				</button>
				<button
					type="button"
					aria-label="Next page"
					disabled={!canNext}
					className={pagerButtonClass}
					onClick={() => {
						onOffsetChange(offset + limit);
					}}
				>
					<ChevronRight className="size-4" />
				</button>
			</div>
		</div>
	);
}

/**
 * Panel-styled data table shared by list pages (agent thread history, users).
 *
 * Layout is a CSS grid so columns can collapse below `md` (`hideBelowMd`,
 * `mobileWidth`); the two grid templates are passed down as CSS variables.
 * Server-side pagination renders as a footer when `pagination` is provided
 * and there is more than one page.
 *
 * Loading UX: the skeleton only shows while the table has nothing to display
 * (initial load). Page/filter changes keep the current rows on screen and dim
 * them — after a short delay so fast responses never flicker — then the new
 * rows fade in (the rows container is keyed by page content to restart the
 * animation).
 */
export function DataTable<T>({
	columns,
	rows,
	rowKey,
	isLoading = false,
	emptyMessage = "No results.",
	getRowHref,
	pagination,
	className = "",
}: DataTableProps<T>) {
	const gridTemplates = {
		"--dt-cols": columns
			.filter((c) => !c.hideBelowMd)
			.map((c) => c.mobileWidth ?? c.width ?? "1fr")
			.join(" "),
		"--dt-cols-md": columns.map((c) => c.width ?? "1fr").join(" "),
	} as CSSProperties;
	const gridClass =
		"grid items-center gap-4 px-[18px] [grid-template-columns:var(--dt-cols)] md:[grid-template-columns:var(--dt-cols-md)]";

	const renderCells = (row: T) =>
		columns.map((column) => (
			<div key={column.key} className={cellClass(column)}>
				{column.cell(row)}
			</div>
		));

	const showSkeleton = isLoading && rows.length === 0;
	// Changes whenever another page (or filter result) lands, restarting the
	// fade-in on the rows container.
	const contentKey = `${pagination?.offset ?? 0}:${rows[0] ? rowKey(rows[0]) : "empty"}`;

	return (
		<div
			style={gridTemplates}
			className={`overflow-hidden rounded-[14px] border border-[#e1ebe6] bg-white dark:border-white/10 dark:bg-card ${className}`}
		>
			<div
				className={`${gridClass} border-b border-[#edf2ef] py-[11px] dark:border-white/5`}
			>
				{columns.map((column) => (
					<span key={column.key} className={`${HEADER_LABEL_CLASS} ${cellClass(column)}`}>
						{column.header}
					</span>
				))}
			</div>

			{showSkeleton ? (
				Array.from({ length: 5 }, (_, i) => (
					<div key={i} className={`${gridClass} ${ROW_CLASS}`}>
						{columns.map((column) => (
							<div key={column.key} className={cellClass(column)}>
								<div className="h-3.5 w-3/4 max-w-[160px] animate-pulse rounded bg-[#eff4f1] dark:bg-white/10" />
							</div>
						))}
					</div>
				))
			) : rows.length === 0 ? (
				<div className="px-[18px] py-12 text-center text-[14px] font-medium text-[#A3B5AD] dark:text-muted-foreground">
					{emptyMessage}
				</div>
			) : (
				<div
					key={contentKey}
					className={`animate-in fade-in duration-300 transition-opacity ${
						isLoading
							? "pointer-events-none opacity-40 delay-150"
							: "opacity-100 delay-0"
					}`}
				>
					{rows.map((row) =>
						getRowHref ? (
							<Link
								key={rowKey(row)}
								href={getRowHref(row)}
								className={`${gridClass} ${ROW_CLASS}`}
							>
								{renderCells(row)}
							</Link>
						) : (
							<div key={rowKey(row)} className={`${gridClass} ${ROW_CLASS}`}>
								{renderCells(row)}
							</div>
						),
					)}
				</div>
			)}

			{pagination && pagination.total > pagination.limit && (
				<PaginationFooter {...pagination} />
			)}
		</div>
	);
}
