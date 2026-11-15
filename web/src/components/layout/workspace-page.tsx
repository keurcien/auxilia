"use client";

import Link from "next/link";
import { Fragment } from "react";

import { PageContainer } from "@/components/layout/page-container";
import type { BreadcrumbSegment } from "@/components/layout/subpage-header";
import { SearchBar } from "@/components/ui/search-bar";
import { cn } from "@/lib/utils";
import { useWorkspacesStore } from "@/stores/workspaces-store";

interface WorkspaceSearch {
	placeholder: string;
	value: string;
	onChange: (value: string) => void;
}

interface WorkspacePageProps {
	/** Breadcrumb segment: `workspace / <slug>` */
	slug: string;
	/** Linked segments between the workspace and `slug`, for nested pages
	 * (e.g. `workspace / agents / <agent> / threads`). */
	parents?: BreadcrumbSegment[];
	title: string;
	intro: string;
	search?: WorkspaceSearch;
	/** Primary action(s) in the top bar — use WorkspaceTopBarButton */
	actions?: React.ReactNode;
	/** Right side of the page header (tabs, view toggles) */
	headerRight?: React.ReactNode;
	/** On tall viewports, pin the page (no page scroll) and give children the
	 * remaining height — for content that scrolls internally (e.g. a capped
	 * table body). Short viewports keep a single page scroll so the header
	 * cannot squeeze the content out of view. */
	fillHeight?: boolean;
	/** Let dense list pages use the full workspace width instead of the
	 * standard reading-width cap. */
	fullWidth?: boolean;
	children: React.ReactNode;
}

/**
 * Shared chrome for workspace pages (Agents, MCP servers, Users, Triggers):
 * a 52px top bar (mono breadcrumb + search + primary action) over a
 * scrollable content area with the Space Grotesk page header.
 */
export function WorkspacePage({
	slug,
	parents = [],
	title,
	intro,
	search,
	actions,
	headerRight,
	fillHeight = false,
	fullWidth = false,
	children,
}: WorkspacePageProps) {
	const workspaceName = useWorkspacesStore((state) =>
		state.workspaces.find((workspace) => workspace.id === state.activeWorkspaceId)?.name,
	);
	return (
		<div className="flex h-svh min-w-0 flex-1 flex-col bg-background">
			{/* pl-14 below md leaves room for the floating sidebar trigger */}
			<header className="flex h-[52px] shrink-0 items-center gap-3 border-b border-border pl-14 pr-4 md:px-8">
				<nav className="flex min-w-0 items-center whitespace-nowrap text-[11.5px] text-meta dark:text-panel-dim">
					<Link
						href="/"
						className="min-w-0 truncate rounded-[3px] transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-petrol/35"
					>
						{workspaceName ?? "workspace"}
					</Link>
					<span className="mx-1.5 shrink-0 text-ghost dark:text-panel-dim">
						/
					</span>
					{parents.map((segment, index) => (
						<Fragment key={`${segment.label}-${index}`}>
							{segment.href ? (
								<Link
									href={segment.href}
									className="min-w-0 truncate rounded-[3px] transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-petrol/35"
								>
									{segment.label}
								</Link>
							) : (
								<span className="min-w-0 truncate">{segment.label}</span>
							)}
							<span className="mx-1.5 shrink-0 text-ghost dark:text-panel-dim">
								/
							</span>
						</Fragment>
					))}
					<span className="max-w-[50%] shrink-0 truncate font-medium text-foreground">
						{slug}
					</span>
				</nav>
				<div className="ml-auto flex shrink-0 items-center gap-2 lg:gap-3">
					{actions}
				</div>
			</header>
			{/* `relative` makes the scroll area the containing block of absolutely
			    positioned descendants (sr-only labels, checkboxes): without it they
			    escape its overflow and extend the document into a second scroll. */}
			<div
				data-workspace-scroll=""
				className={cn(
					"relative min-h-0 flex-1 overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
					fillHeight && "flex flex-col tall:overflow-hidden",
				)}
			>
				<PageContainer
					className={cn(
						"px-4 pt-8 pb-[calc(2.5rem+env(safe-area-inset-bottom))] sm:px-6 lg:px-8",
						fillHeight && "tall:flex tall:min-h-0 tall:flex-1 tall:flex-col",
						fullWidth && "@min-screen-xl/layout:max-w-none",
					)}
				>
					<div className="grid shrink-0 grid-cols-1 gap-y-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end lg:gap-x-6">
						<div className="min-w-0 lg:col-start-1">
							<h1 className="font-display text-[30px] font-bold tracking-[-0.035em] text-foreground">
								{title}
							</h1>
							<p className="mt-2 max-w-[560px] text-[15px] leading-[1.6] text-body dark:text-panel-body text-pretty">
								{intro}
							</p>
							{search && (
								<SearchBar
									placeholder={search.placeholder}
									value={search.value}
									onChange={search.onChange}
									hint="⌘K"
									focusOnModK
									className="mt-5 w-full lg:max-w-[560px]"
								/>
							)}
						</div>
						{headerRight && (
							<div className="flex w-full min-w-0 items-center lg:col-start-2 lg:row-span-1 lg:row-start-1 lg:w-auto lg:self-end">
								{headerRight}
							</div>
						)}
					</div>
					<div
						className={cn(
							"mt-4",
							fillHeight && "tall:flex tall:min-h-0 tall:flex-1 tall:flex-col",
						)}
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
