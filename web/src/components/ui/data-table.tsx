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
	/** Noun appended to the count, already pluralized (e.g. "agents"). */
	itemLabel?: string;
}

interface DataTableProps<T> {
	columns: DataTableColumn<T>[];
	rows: T[];
	rowKey: (row: T) => string;
	isLoading?: boolean;
	emptyMessage?: ReactNode;
	/** When set, each row renders as a link to this href. */
	getRowHref?: (row: T) => string;
	/** Click handler alternative to `getRowHref` for rows that need logic
	 * before navigating (permission checks, dialogs…). */
	onRowClick?: (row: T) => void;
	/** Optional row grouping: consecutive rows sharing a key get a subheader
	 * row above the first one. Rows must arrive pre-sorted by group. */
	groupBy?: {
		key: (row: T) => string;
		header: (key: string) => ReactNode;
	};
	/** Cap the rows container at the available height and scroll it
	 * internally. Needs a bounded-height flex ancestry (e.g. WorkspacePage
	 * with `fillHeight`); the container still hugs its content when short. */
	scrollBody?: boolean;
	pagination?: DataTablePagination;
	className?: string;
}

const HEADER_LABEL_CLASS =
	"font-mono text-[10px] font-semibold uppercase tracking-[0.09em] text-meta dark:text-panel-dim";
const ROW_CLASS =
	"group border-b border-hairline py-[11px] transition-colors duration-[110ms] last:border-b-0 hover:bg-sidebar dark:border-white/5 dark:hover:bg-white/5";
const PAGER_BUTTON_CLASS =
	"flex size-7 items-center justify-center rounded-[7px] border border-border font-mono text-[11.5px] font-medium text-subtle cursor-pointer transition-colors hover:bg-sidebar disabled:cursor-default disabled:opacity-40 disabled:hover:bg-transparent dark:border-white/10 dark:text-muted-foreground dark:hover:bg-white/5";

function cellClass(column: Pick<DataTableColumn<never>, "hideBelowMd" | "align">): string {
	return [
		"min-w-0",
		column.hideBelowMd ? "hidden md:block" : "",
		column.align === "right" ? "text-right" : "",
	]
		.filter(Boolean)
		.join(" ");
}

/** Page indices to render as numbered squares: all of them when few, else
 * first/last/current±1 with `null` gaps for the ellipses. */
function pageItems(pageCount: number, current: number): (number | null)[] {
	if (pageCount <= 7) {
		return Array.from({ length: pageCount }, (_, i) => i);
	}
	const wanted = new Set(
		[0, pageCount - 1, current - 1, current, current + 1].filter(
			(page) => page >= 0 && page < pageCount,
		),
	);
	const items: (number | null)[] = [];
	for (const page of [...wanted].sort((a, b) => a - b)) {
		const prev = items[items.length - 1];
		if (typeof prev === "number" && page - prev > 1) items.push(null);
		items.push(page);
	}
	return items;
}

/** Below-container footer: mono range count left, numbered pager right
 * (design 7a — active page is a filled petrol square). */
function PaginationFooter({
	total,
	limit,
	offset,
	onOffsetChange,
	itemLabel,
}: DataTablePagination) {
	const pageCount = Math.max(1, Math.ceil(total / limit));
	const currentPage = Math.min(Math.floor(offset / limit), pageCount - 1);
	const start = offset + 1;
	const end = Math.min(offset + limit, total);

	return (
		<div className="flex items-center justify-between px-1 py-3.5">
			<span className="font-mono text-[11px] text-meta dark:text-panel-dim">
				{start}–{end} of {total}
				{itemLabel ? ` ${itemLabel}` : ""}
			</span>
			{pageCount > 1 && (
				<span className="flex items-center gap-1">
					<button
						type="button"
						aria-label="Previous page"
						disabled={currentPage === 0}
						className={PAGER_BUTTON_CLASS}
						onClick={() => {
							onOffsetChange(Math.max(0, offset - limit));
						}}
					>
						<ChevronLeft className="size-3.5" />
					</button>
					{pageItems(pageCount, currentPage).map((page, i) =>
						page === null ? (
							<span
								key={`gap-${i}`}
								className="px-0.5 font-mono text-[11.5px] text-ghost dark:text-panel-dim"
							>
								…
							</span>
						) : (
							<button
								key={page}
								type="button"
								aria-label={`Page ${page + 1}`}
								aria-current={page === currentPage ? "page" : undefined}
								onClick={() => {
									onOffsetChange(page * limit);
								}}
								className={
									page === currentPage
										? "flex size-7 cursor-pointer items-center justify-center rounded-[7px] bg-petrol font-mono text-[11.5px] font-semibold text-white"
										: PAGER_BUTTON_CLASS
								}
							>
								{page + 1}
							</button>
						),
					)}
					<button
						type="button"
						aria-label="Next page"
						disabled={currentPage >= pageCount - 1}
						className={PAGER_BUTTON_CLASS}
						onClick={() => {
							onOffsetChange(offset + limit);
						}}
					>
						<ChevronRight className="size-3.5" />
					</button>
				</span>
			)}
		</div>
	);
}

/**
 * Panel-styled data table shared by list pages (agents, MCP servers, users,
 * agent thread history): mono column headers above a bordered rows container,
 * mono count + numbered pagination below it (design 7a/13b/13c).
 *
 * Layout is a CSS grid so columns can collapse below `md` (`hideBelowMd`,
 * `mobileWidth`); the two grid templates are passed down as CSS variables.
 * Rows link (`getRowHref`) or run a click handler (`onRowClick`); pagination
 * can be server-side or a client-side slice — the caller owns `rows` either
 * way. The footer renders whenever `pagination` is provided and there are
 * rows to count; the pager appears only past one page.
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
	onRowClick,
	groupBy,
	scrollBody = false,
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
			className={`${scrollBody ? "flex min-h-0 flex-col " : ""}${className}`}
		>
			<div className={`${gridClass} shrink-0 pb-2 pt-1`}>
				{columns.map((column) => (
					<span key={column.key} className={`${HEADER_LABEL_CLASS} ${cellClass(column)}`}>
						{column.header}
					</span>
				))}
			</div>

			<div
				className={`rounded-[10px] border border-border bg-card dark:border-white/10 ${
					scrollBody
						? "min-h-0 overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
						: "overflow-hidden"
				}`}
			>
				{showSkeleton ? (
					Array.from({ length: 5 }, (_, i) => (
						<div key={i} className={`${gridClass} ${ROW_CLASS}`}>
							{columns.map((column) => (
								<div key={column.key} className={cellClass(column)}>
									<div className="h-3.5 w-3/4 max-w-[160px] animate-pulse rounded bg-hover dark:bg-white/10" />
								</div>
							))}
						</div>
					))
				) : rows.length === 0 ? (
					<div className="px-[18px] py-12 text-center text-[14px] font-medium text-faint dark:text-muted-foreground">
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
						{rows.flatMap((row, index) => {
							const elements: ReactNode[] = [];
							if (groupBy) {
								const groupKey = groupBy.key(row);
								const prevKey = index > 0 ? groupBy.key(rows[index - 1]) : null;
								if (groupKey !== prevKey) {
									// Opaque background (incl. dark) — the header is sticky in
									// scrollBody mode, so rows must not show through it.
									elements.push(
										<div
											key={`group:${groupKey}`}
											className="sticky top-0 z-[1] flex items-center border-b border-hairline bg-sidebar px-[18px] py-[9px] dark:border-white/5 dark:bg-[#1c2830]"
										>
											{groupBy.header(groupKey)}
										</div>,
									);
								}
							}
							if (getRowHref) {
								elements.push(
									<Link
										key={rowKey(row)}
										href={getRowHref(row)}
										className={`${gridClass} ${ROW_CLASS}`}
									>
										{renderCells(row)}
									</Link>,
								);
							} else if (onRowClick) {
								elements.push(
									<div
										key={rowKey(row)}
										onClick={() => {
											onRowClick(row);
										}}
										className={`${gridClass} ${ROW_CLASS} cursor-pointer`}
									>
										{renderCells(row)}
									</div>,
								);
							} else {
								elements.push(
									<div key={rowKey(row)} className={`${gridClass} ${ROW_CLASS}`}>
										{renderCells(row)}
									</div>,
								);
							}
							return elements;
						})}
					</div>
				)}
			</div>

			{pagination && pagination.total > 0 && (
				<PaginationFooter {...pagination} />
			)}
		</div>
	);
}
