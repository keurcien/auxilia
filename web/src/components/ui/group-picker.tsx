"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, Folder, Plus, X } from "lucide-react";
import { normalizeGroup } from "@/lib/groups";
import { cn } from "@/lib/utils";

interface GroupPickerProps {
	value: string;
	groups: string[];
	onChange: (group: string) => void;
}

export function GroupPicker({ value, groups, onChange }: GroupPickerProps) {
	const rootRef = useRef<HTMLDivElement>(null);
	const inputRef = useRef<HTMLInputElement>(null);
	const [open, setOpen] = useState(false);
	const [query, setQuery] = useState("");
	const [activeIndex, setActiveIndex] = useState(0);

	const normalizedQuery = normalizeGroup(query);
	const availableGroups = value ? [...new Set([...groups, value])] : groups;
	const term = query.trim().toLocaleLowerCase();
	const filtered = availableGroups
		.filter((group) => !term || group.toLocaleLowerCase().includes(term))
		.sort((a, b) => a.localeCompare(b));
	const canCreate =
		normalizedQuery.length > 0 &&
		!availableGroups.some(
			(group) =>
				group.toLocaleLowerCase() === normalizedQuery.toLocaleLowerCase(),
		);
	const items = canCreate ? [...filtered, normalizedQuery] : filtered;

	useEffect(() => {
		if (!open) return;
		inputRef.current?.focus();
		const close = (event: MouseEvent) => {
			if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
		};
		document.addEventListener("mousedown", close);
		return () => {
			document.removeEventListener("mousedown", close);
		};
	}, [open]);

	const choose = (group: string) => {
		onChange(group);
		setQuery("");
		setOpen(false);
	};

	return (
		<div ref={rootRef} className="relative">
			<label className="mb-1.5 block text-[11px] font-semibold text-label dark:text-muted-foreground">
				Group <span className="font-normal text-meta">(Optional)</span>
			</label>
			<div
				className={cn(
					"flex h-9 items-center rounded-lg border border-input bg-card transition-[border-color,box-shadow]",
					open &&
						"border-petrol shadow-[0_0_0_3px_rgba(22,96,110,0.10)]",
				)}
			>
				<button
					type="button"
					aria-haspopup="listbox"
					aria-expanded={open}
					onClick={() => {
						setOpen((current) => !current);
					}}
					className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 px-3 text-left"
				>
					<Folder className="size-4 shrink-0 text-meta" />
					<span
						className={cn(
							"min-w-0 flex-1 truncate text-[12.5px]",
							value
								? "font-medium text-foreground"
								: "text-meta dark:text-panel-dim",
						)}
					>
						{value || "Group name"}
					</span>
					<ChevronDown
						className={cn(
							"size-3.5 shrink-0 text-meta transition-transform",
							open && "rotate-180",
						)}
					/>
				</button>
				{value && (
					<button
						type="button"
						aria-label="Clear group"
						onClick={() => {
							onChange("");
							setQuery("");
						}}
						className="mr-2 flex size-5 cursor-pointer items-center justify-center rounded text-meta hover:bg-sidebar hover:text-foreground"
					>
						<X className="size-3" />
					</button>
				)}
			</div>

			{open && (
				<div className="absolute left-0 right-0 top-full z-50 mt-1 overflow-hidden rounded-xl border border-border bg-card shadow-[0_14px_40px_rgba(16,24,32,0.14)] dark:border-white/10">
					<div className="border-b border-border p-2.5 dark:border-white/10">
						<input
							ref={inputRef}
							value={query}
							maxLength={255}
							placeholder="Search or create group…"
							onChange={(event) => {
								setQuery(event.target.value);
								setActiveIndex(0);
							}}
							onKeyDown={(event) => {
								if (event.key === "Escape") {
									setOpen(false);
									return;
								}
								if (event.key === "ArrowDown") {
									event.preventDefault();
									setActiveIndex((index) =>
										Math.min(index + 1, Math.max(items.length - 1, 0)),
									);
								}
								if (event.key === "ArrowUp") {
									event.preventDefault();
									setActiveIndex((index) => Math.max(index - 1, 0));
								}
								if (event.key === "Enter") {
									const activeItem = items.at(activeIndex);
									if (activeItem) {
										event.preventDefault();
										choose(activeItem);
									}
								}
							}}
							className="h-9 w-full rounded-lg border border-input bg-background px-3 text-[12.5px] text-foreground outline-none placeholder:text-meta focus:border-petrol"
						/>
					</div>
					<div role="listbox" className="max-h-56 overflow-y-auto p-1.5">
						{filtered.map((group, index) => (
							<button
								key={group}
								type="button"
								role="option"
								aria-selected={value === group}
								onMouseEnter={() => {
									setActiveIndex(index);
								}}
								onClick={() => {
									choose(group);
								}}
								className={cn(
									"flex w-full cursor-pointer items-center gap-2 rounded-lg px-3 py-2.5 text-left text-[12.5px] transition-colors",
									activeIndex === index
										? "bg-sidebar text-foreground dark:bg-white/5"
										: "text-body dark:text-panel-body",
								)}
							>
								<Folder className="size-4 shrink-0 text-meta" />
								<span className="truncate">{group}</span>
							</button>
						))}
						{canCreate && (
							<button
								type="button"
								onMouseEnter={() => {
									setActiveIndex(filtered.length);
								}}
								onClick={() => {
									choose(normalizedQuery);
								}}
								className={cn(
									"flex w-full cursor-pointer items-center gap-2 rounded-lg px-3 py-2.5 text-left text-[12.5px] font-medium text-petrol transition-colors dark:text-panel-terminal",
									activeIndex === filtered.length &&
										"bg-petrol-tint dark:bg-white/5",
								)}
							>
								<Plus className="size-4 shrink-0" />
								<span className="truncate">Create “{normalizedQuery}”</span>
							</button>
						)}
						{filtered.length === 0 && !canCreate && (
							<p className="px-3 py-4 text-center text-[12px] text-meta">
								Type a group name
							</p>
						)}
					</div>
				</div>
			)}
		</div>
	);
}
