"use client";

import { useMemo, useRef, useState } from "react";
import * as DropdownMenuPrimitive from "@radix-ui/react-dropdown-menu";
import { Check, ChevronDown, Search } from "lucide-react";

interface TimezonePickerProps {
	value: string;
	onChange: (timezone: string) => void;
}

const TIMEZONES = [
	"UTC",
	...Intl.supportedValuesOf("timeZone").filter((timezone) => timezone !== "UTC"),
];

function matchesQuery(timezone: string, query: string): boolean {
	const normalizedQuery = query.trim().toLowerCase().replaceAll(" ", "_");
	return timezone.toLowerCase().includes(normalizedQuery);
}

export default function TimezonePicker({
	value,
	onChange,
}: TimezonePickerProps) {
	const [open, setOpen] = useState(false);
	const [query, setQuery] = useState("");
	const inputRef = useRef<HTMLInputElement>(null);
	const timezones = useMemo(
		() => TIMEZONES.filter((timezone) => matchesQuery(timezone, query)),
		[query],
	);

	const handleOpenChange = (nextOpen: boolean) => {
		setOpen(nextOpen);
		if (nextOpen) {
			requestAnimationFrame(() => {
				inputRef.current?.focus();
			});
		} else {
			setQuery("");
		}
	};

	return (
		<DropdownMenuPrimitive.Root open={open} onOpenChange={handleOpenChange}>
			<DropdownMenuPrimitive.Trigger asChild>
				<button
					type="button"
					className="flex h-11 w-full items-center justify-between rounded-lg border border-input bg-card px-3.5 text-left text-[13px] font-medium text-foreground transition-colors hover:border-border-hover dark:border-white/10 dark:bg-transparent"
				>
					<span className="truncate font-mono">{value}</span>
					<ChevronDown className="size-4 shrink-0 text-faint" />
				</button>
			</DropdownMenuPrimitive.Trigger>

			<DropdownMenuPrimitive.Portal>
				<DropdownMenuPrimitive.Content
					align="start"
					sideOffset={6}
					className="z-50 w-[var(--radix-dropdown-menu-trigger-width)] min-w-[280px] overflow-hidden rounded-[10px] border border-hairline bg-canvas shadow-[0_12px_32px_-12px_rgba(10,25,30,0.18)] data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:slide-in-from-top-1 dark:border-white/10 dark:bg-card"
				>
					<div className="border-b border-hairline p-2 dark:border-white/10">
						<div className="flex h-9 items-center gap-2 rounded-md bg-sidebar px-2.5 dark:bg-white/5">
							<Search className="size-3.5 shrink-0 text-faint" />
							<input
								ref={inputRef}
								value={query}
								onChange={(event) => {
									setQuery(event.target.value);
								}}
								onKeyDown={(event) => {
									if (event.key.length === 1) {
										event.stopPropagation();
									}
								}}
								placeholder="Search timezone…"
								className="min-w-0 flex-1 bg-transparent text-[12.5px] text-foreground outline-none placeholder:text-faint"
							/>
						</div>
					</div>

					<div className="max-h-64 overflow-y-auto p-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
						{timezones.map((timezone) => (
							<DropdownMenuPrimitive.Item
								key={timezone}
								onSelect={() => {
									onChange(timezone);
									handleOpenChange(false);
								}}
								className="flex cursor-pointer select-none items-center rounded-[6px] px-2.5 py-2 font-mono text-[12px] text-ink outline-none transition-colors focus:bg-hover dark:text-panel-button dark:focus:bg-white/5"
							>
								<span className="truncate">{timezone}</span>
								{timezone === value && (
									<Check
										className="ml-auto size-3.5 shrink-0 text-petrol dark:text-panel-terminal"
										strokeWidth={3}
									/>
								)}
							</DropdownMenuPrimitive.Item>
						))}
						{timezones.length === 0 && (
							<p className="px-3 py-6 text-center text-[12px] text-meta dark:text-panel-dim">
								No timezone found.
							</p>
						)}
					</div>
				</DropdownMenuPrimitive.Content>
			</DropdownMenuPrimitive.Portal>
		</DropdownMenuPrimitive.Root>
	);
}
