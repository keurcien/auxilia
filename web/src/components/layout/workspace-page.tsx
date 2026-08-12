"use client";

import { PageContainer } from "@/components/layout/page-container";
import { SearchBar } from "@/components/ui/search-bar";
import { cn } from "@/lib/utils";

interface WorkspaceSearch {
	placeholder: string;
	value: string;
	onChange: (value: string) => void;
}

interface WorkspacePageProps {
	/** Breadcrumb segment: `workspace / <slug>` */
	slug: string;
	title: string;
	intro: string;
	search?: WorkspaceSearch;
	/** Primary action(s) in the top bar — use WorkspaceTopBarButton */
	actions?: React.ReactNode;
	/** Right side of the page header (tabs, view toggles) */
	headerRight?: React.ReactNode;
	/** Pin the page (no page scroll) and give children the remaining height —
	 * for content that scrolls internally (e.g. a capped table body). */
	fillHeight?: boolean;
	children: React.ReactNode;
}

/**
 * Shared chrome for workspace pages (Agents, MCP servers, Users, Triggers):
 * a 52px top bar (mono breadcrumb + search + primary action) over a
 * scrollable content area with the Space Grotesk page header.
 */
export function WorkspacePage({
	slug,
	title,
	intro,
	search,
	actions,
	headerRight,
	fillHeight = false,
	children,
}: WorkspacePageProps) {
	return (
		<div className="flex h-svh min-w-0 flex-1 flex-col bg-background">
			{/* pl-14 below md leaves room for the floating sidebar trigger */}
			<header className="flex h-[52px] shrink-0 items-center gap-3 border-b border-border pl-14 pr-4 md:px-8">
				<span className="font-mono text-[11.5px] text-meta dark:text-panel-dim">
					workspace <span className="text-ghost dark:text-panel-dim">/</span>{" "}
					<span className="font-medium text-foreground">{slug}</span>
				</span>
				<div className="ml-auto flex items-center gap-3">
					{search && (
						<SearchBar
							placeholder={search.placeholder}
							value={search.value}
							onChange={search.onChange}
							hint="⌘K"
							className="hidden w-80 sm:block"
						/>
					)}
					{actions}
				</div>
			</header>
			<div
				className={
					fillHeight
						? "flex min-h-0 flex-1 flex-col overflow-hidden"
						: "flex-1 overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
				}
			>
				<PageContainer
					className={cn(
						"px-4 pt-8 pb-10 sm:px-6 lg:px-8",
						fillHeight && "flex min-h-0 flex-1 flex-col",
					)}
				>
					<div className="flex shrink-0 flex-wrap items-end justify-between gap-x-6 gap-y-4">
						<div className="min-w-0">
							<h1 className="font-display text-[30px] font-bold tracking-[-0.035em] text-foreground">
								{title}
							</h1>
							<p className="mt-2 max-w-[560px] text-[15px] leading-[1.6] text-body dark:text-panel-body text-pretty">
								{intro}
							</p>
						</div>
						{headerRight}
					</div>
					<div
						className={
							fillHeight ? "mt-4 flex min-h-0 flex-1 flex-col" : "mt-4"
						}
					>
						{children}
					</div>
				</PageContainer>
			</div>
		</div>
	);
}

/** Ink primary-action button for the workspace top bar. */
export function WorkspaceTopBarButton({
	className,
	children,
	...props
}: React.ComponentProps<"button">) {
	return (
		<button
			type="button"
			className={cn(
				"flex shrink-0 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-[7px] bg-primary px-[18px] py-[9px] text-[13.5px] font-semibold text-primary-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50",
				className,
			)}
			{...props}
		>
			{children}
		</button>
	);
}
