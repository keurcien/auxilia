"use client";

import * as DropdownMenuPrimitive from "@radix-ui/react-dropdown-menu";
import { Check, ChevronsUpDown, Loader2, Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

export interface AsyncSearchOption {
	value: string;
	label: string;
	description?: string;
}

interface AsyncSearchSelectProps {
	label: string;
	value: string | null;
	selectedOption?: AsyncSearchOption | null;
	placeholder: string;
	emptyValueLabel: string;
	disabled?: boolean;
	loadOptions: (
		query: string,
		signal: AbortSignal,
	) => Promise<AsyncSearchOption[]>;
	onChange: (value: string | null, option: AsyncSearchOption | null) => void;
}

export function AsyncSearchSelect({
	label,
	value,
	selectedOption,
	placeholder,
	emptyValueLabel,
	disabled = false,
	loadOptions,
	onChange,
}: AsyncSearchSelectProps) {
	const searchRef = useRef<HTMLInputElement>(null);
	const [open, setOpen] = useState(false);
	const [query, setQuery] = useState("");
	const [options, setOptions] = useState<AsyncSearchOption[]>([]);
	const [loading, setLoading] = useState(false);
	const [failed, setFailed] = useState(false);

	useEffect(() => {
		if (!open || disabled) return;
		const controller = new AbortController();
		const timeout = window.setTimeout(() => {
			setLoading(true);
			setFailed(false);
			void loadOptions(query.trim(), controller.signal)
				.then((results) => {
					if (!controller.signal.aborted) setOptions(results);
				})
				.catch(() => {
					if (!controller.signal.aborted) setFailed(true);
				})
				.finally(() => {
					if (!controller.signal.aborted) setLoading(false);
				});
		}, 300);
		return () => {
			window.clearTimeout(timeout);
			controller.abort();
		};
	}, [disabled, loadOptions, open, query]);

	useEffect(() => {
		if (!open) return;
		const frame = requestAnimationFrame(() => {
			searchRef.current?.focus();
		});
		return () => {
			cancelAnimationFrame(frame);
		};
	}, [open]);

	const selectedLabel =
		value === null
			? emptyValueLabel
			: (selectedOption?.label ?? "Selected item");

	return (
		<label className="block min-w-0">
			<span className="mb-1.5 block text-[11px] font-semibold text-label dark:text-muted-foreground">
				{label}
			</span>
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
				<DropdownMenuPrimitive.Trigger asChild disabled={disabled}>
					<button
						type="button"
						className="flex h-10 w-full cursor-pointer items-center gap-2 rounded-[9px] border border-input bg-card px-3 text-left outline-none transition-[border-color,box-shadow] hover:border-border-hover focus-visible:border-petrol focus-visible:shadow-[0_0_0_3px_rgba(22,96,110,0.10)] disabled:cursor-not-allowed disabled:opacity-50"
					>
						<span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-foreground">
							{selectedLabel}
						</span>
						<ChevronsUpDown className="size-3.5 shrink-0 text-meta" />
					</button>
				</DropdownMenuPrimitive.Trigger>
				<DropdownMenuPrimitive.Portal>
					<DropdownMenuPrimitive.Content
						align="start"
						sideOffset={5}
						collisionPadding={16}
						className="z-[70] w-[var(--radix-dropdown-menu-trigger-width)] min-w-64 overflow-hidden rounded-[11px] border border-border bg-card shadow-[0_18px_50px_rgba(10,25,30,0.16)] dark:border-white/10"
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
										event.stopPropagation();
									}}
									aria-label={`Search ${label.toLocaleLowerCase()}`}
									placeholder={placeholder}
									className="h-9 w-full rounded-[7px] border border-input bg-background pl-8 pr-3 text-[12.5px] text-foreground outline-none placeholder:text-meta focus:border-petrol"
								/>
							</div>
						</div>
						<div className="max-h-64 overflow-y-auto p-1.5">
							<DropdownMenuPrimitive.Item
								onSelect={() => {
									onChange(null, null);
								}}
								className={cn(
									"flex cursor-pointer items-center gap-2 rounded-[7px] px-3 py-2.5 text-[12.5px] text-foreground outline-none data-[highlighted]:bg-sidebar",
									value === null && "bg-petrol-tint dark:bg-white/5",
								)}
							>
								<span className="min-w-0 flex-1 truncate">
									{emptyValueLabel}
								</span>
								{value === null && (
									<Check className="size-3.5 shrink-0 text-petrol" />
								)}
							</DropdownMenuPrimitive.Item>
							{options.map((option) => (
								<DropdownMenuPrimitive.Item
									key={option.value}
									onSelect={() => {
										onChange(option.value, option);
									}}
									className={cn(
										"flex cursor-pointer items-center gap-2 rounded-[7px] px-3 py-2.5 text-foreground outline-none data-[highlighted]:bg-sidebar",
										value === option.value &&
											"bg-petrol-tint dark:bg-white/5",
									)}
								>
									<span className="min-w-0 flex-1">
										<span className="block truncate text-[12.5px] font-medium">
											{option.label}
										</span>
										{option.description && (
											<span className="mt-0.5 block truncate text-[10.5px] text-meta">
												{option.description}
											</span>
										)}
									</span>
									{value === option.value && (
										<Check className="size-3.5 shrink-0 text-petrol" />
									)}
								</DropdownMenuPrimitive.Item>
							))}
							{loading && (
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
									No results found.
								</p>
							)}
						</div>
					</DropdownMenuPrimitive.Content>
				</DropdownMenuPrimitive.Portal>
			</DropdownMenuPrimitive.Root>
		</label>
	);
}
