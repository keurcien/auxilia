"use client";

import * as DropdownMenuPrimitive from "@radix-ui/react-dropdown-menu";
import {
	AlarmClock,
	Bot,
	Check,
	ChevronDown,
	Folder,
	ListFilter,
	Loader2,
	Search,
	User,
} from "lucide-react";
import { Fragment, useEffect, useRef, useState } from "react";
import { VendorMark } from "@/components/usage/usage-badge";
import { searchUsageFilterOptions } from "@/lib/api/resources/usage";
import { formatMoney } from "@/lib/usage/format";
import { cn } from "@/lib/utils";
import type { UsageFilterOption, UsageScope } from "@/types/usage";
import { DIMENSION_LABELS, type FilterDimension } from "./usage-breakdown";

const SEARCH_DELAY_MS = 300;

const DIMENSION_ICONS: Partial<Record<FilterDimension, typeof Folder>> = {
	project: Folder,
	user: User,
	agent: Bot,
	trigger: AlarmClock,
};

/** Focus the report on a project, vendor, model, user, agent or trigger. */
export function UsageFilterSearch({
	scope,
	currency,
	activeFilters,
	onSelect,
}: {
	scope: UsageScope | undefined;
	currency: string;
	activeFilters: Partial<Record<FilterDimension, string>>;
	onSelect: (dimension: FilterDimension, key: string) => void;
}) {
	const searchRef = useRef<HTMLInputElement>(null);
	const listRef = useRef<HTMLDivElement>(null);
	const [open, setOpen] = useState(false);
	const [query, setQuery] = useState("");
	const [options, setOptions] = useState<UsageFilterOption[]>([]);
	const [loading, setLoading] = useState(false);
	const [failed, setFailed] = useState(false);

	useEffect(() => {
		if (!open) return;
		const controller = new AbortController();
		const timeout = window.setTimeout(() => {
			void searchUsageFilterOptions(query.trim(), scope, controller.signal)
				.then((results) => {
					if (controller.signal.aborted) return;
					setOptions(results);
					setFailed(false);
				})
				.catch(() => {
					if (!controller.signal.aborted) setFailed(true);
				})
				.finally(() => {
					if (!controller.signal.aborted) setLoading(false);
				});
		}, SEARCH_DELAY_MS);
		return () => {
			window.clearTimeout(timeout);
			controller.abort();
		};
	}, [open, query, scope]);

	useEffect(() => {
		if (!open) return;
		const frame = requestAnimationFrame(() => {
			searchRef.current?.focus();
		});
		return () => {
			cancelAnimationFrame(frame);
		};
	}, [open]);

	const select = (option: UsageFilterOption) => {
		onSelect(option.dimension as FilterDimension, option.key);
		setOpen(false);
	};

	return (
		<DropdownMenuPrimitive.Root
			open={open}
			onOpenChange={(next) => {
				setOpen(next);
				if (next) {
					setQuery("");
					setLoading(true);
				}
			}}
			modal={false}
		>
			<DropdownMenuPrimitive.Trigger asChild>
				<button
					type="button"
					className="flex cursor-pointer items-center gap-2 whitespace-nowrap rounded-[8px] border border-input px-3 py-[7px] text-[12.5px] font-semibold text-foreground transition-colors hover:border-border-hover data-[state=open]:border-border-hover dark:border-white/10"
				>
					<ListFilter className="size-3.5 text-meta" />
					Filter
					<ChevronDown className="size-3.5 text-meta" />
				</button>
			</DropdownMenuPrimitive.Trigger>
			<DropdownMenuPrimitive.Portal>
				<DropdownMenuPrimitive.Content
					align="end"
					sideOffset={6}
					collisionPadding={16}
					className="z-50 w-[340px] overflow-hidden rounded-[11px] border border-border bg-card shadow-[0_18px_50px_rgba(10,25,30,0.16)] dark:border-white/10"
				>
					<div className="border-b border-border p-2">
						<div className="relative">
							<Search className="absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-meta" />
							<input
								ref={searchRef}
								value={query}
								onChange={(event) => {
									setQuery(event.target.value);
									setLoading(true);
								}}
								onKeyDown={(event) => {
									if (event.key === "ArrowDown") {
										event.preventDefault();
										listRef.current
											?.querySelector<HTMLElement>('[role="menuitem"]')
											?.focus();
										return;
									}
									if (event.key === "Enter" && !loading && options[0]) {
										event.preventDefault();
										select(options[0]);
										return;
									}
									if (event.key !== "Escape") event.stopPropagation();
								}}
								aria-label="Search projects, vendors, models, users, agents and triggers"
								placeholder="Project, vendor, model, user…"
								className="h-9 w-full rounded-[7px] border border-input bg-background pl-8 pr-3 text-[12.5px] text-foreground outline-none placeholder:text-meta focus:border-petrol"
							/>
						</div>
					</div>
					<div
						ref={listRef}
						className={cn(
							"max-h-[360px] overflow-y-auto p-1.5 transition-opacity",
							loading && options.length > 0 && "opacity-60",
						)}
					>
						{options.map((option, index) => {
							const dimension = option.dimension as FilterDimension;
							const Icon = DIMENSION_ICONS[dimension];
							const active = activeFilters[dimension] === option.key;
							const firstOfGroup =
								index === 0 || options[index - 1].dimension !== option.dimension;
							return (
								<Fragment key={`${option.dimension}-${option.key}`}>
									{firstOfGroup && (
										<DropdownMenuPrimitive.Label className="px-2.5 pb-1 pt-2 text-[11px] font-semibold text-meta dark:text-panel-dim">
											{DIMENSION_LABELS[dimension].tab}
										</DropdownMenuPrimitive.Label>
									)}
									<DropdownMenuPrimitive.Item
										onSelect={() => {
											select(option);
										}}
										className={cn(
											"flex cursor-pointer items-center gap-2.5 rounded-[7px] px-2.5 py-2 text-foreground outline-none data-[highlighted]:bg-sidebar",
											active && "bg-petrol-tint dark:bg-white/5",
										)}
									>
										{Icon ? (
											<Icon className="size-3.5 shrink-0 text-meta" />
										) : (
											<VendorMark vendor={option.vendor} />
										)}
										<span className="min-w-0 flex-1 truncate text-[12.5px] font-medium">
											{option.label}
										</span>
										<span className="shrink-0 font-mono text-[11.5px] tabular-nums text-meta">
											{formatMoney(option.cost, currency)}
										</span>
										{active && <Check className="size-3.5 shrink-0 text-petrol" />}
									</DropdownMenuPrimitive.Item>
								</Fragment>
							);
						})}
						{loading && options.length === 0 && (
							<div className="flex items-center justify-center gap-2 px-3 py-6 text-[11.5px] text-meta">
								<Loader2 className="size-3.5 animate-spin" />
								Searching…
							</div>
						)}
						{!loading && failed && (
							<p className="px-3 py-6 text-center text-[11.5px] text-destructive">
								Search could not be loaded.
							</p>
						)}
						{!loading && !failed && options.length === 0 && (
							<p className="px-3 py-6 text-center text-[11.5px] text-meta">
								{query.trim() ? "Nothing with usage matches." : "No usage recorded yet."}
							</p>
						)}
					</div>
				</DropdownMenuPrimitive.Content>
			</DropdownMenuPrimitive.Portal>
		</DropdownMenuPrimitive.Root>
	);
}
