"use client";

import { useRef, useState } from "react";
import { Check, ChevronDown, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { matchesQuery } from "@/lib/quick-search";
import { handleKeyboardListNavigation } from "@/lib/keyboard-list-navigation";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import {
	Popover,
	PopoverContent,
	PopoverTrigger,
} from "@/components/ui/popover";
import type { Agent } from "@/types/agents";

interface AgentMultiPickerProps {
	/** The agents that may be picked, in display order. */
	agents: Agent[];
	value: string[];
	onChange: (agentIds: string[]) => void;
	placeholder?: string;
	disabled?: boolean;
}

const MAX_CHIPS = 3;

/** A searchable dropdown that picks one or more agents. */
export function AgentMultiPicker({
	agents,
	value,
	onChange,
	placeholder = "Select agents",
	disabled,
}: AgentMultiPickerProps) {
	const searchRef = useRef<HTMLInputElement>(null);
	const [open, setOpen] = useState(false);
	const [query, setQuery] = useState("");

	const selected = agents.filter((agent) => value.includes(agent.id));
	const visible = agents.filter((agent) =>
		matchesQuery(query, agent.name, agent.description, agent.group),
	);
	const allVisibleSelected =
		visible.length > 0 && visible.every((agent) => value.includes(agent.id));

	const toggle = (agentId: string) => {
		onChange(
			value.includes(agentId)
				? value.filter((id) => id !== agentId)
				: [...value, agentId],
		);
	};

	const toggleVisible = () => {
		const visibleIds = new Set(visible.map((agent) => agent.id));
		onChange(
			allVisibleSelected
				? value.filter((id) => !visibleIds.has(id))
				: [...new Set([...value, ...visibleIds])],
		);
	};

	return (
		<Popover
			open={open}
			onOpenChange={(nextOpen) => {
				setOpen(nextOpen);
				if (!nextOpen) setQuery("");
			}}
		>
			<PopoverTrigger asChild disabled={disabled}>
				<button
					type="button"
					aria-label={placeholder}
					className={cn(
						"flex min-h-[46px] w-full cursor-pointer items-center gap-2 rounded-[10px] border border-input bg-card px-3 py-2 text-left outline-none transition-[border-color,box-shadow] hover:border-border-hover focus-visible:border-petrol focus-visible:shadow-[0_0_0_3px_rgba(22,96,110,0.10)] disabled:cursor-default disabled:opacity-60",
						open &&
							"border-petrol shadow-[0_0_0_3px_rgba(22,96,110,0.10)]",
					)}
				>
					{selected.length === 0 ? (
						<span className="flex-1 text-[13px] font-medium text-meta dark:text-panel-dim">
							{placeholder}
						</span>
					) : (
						<span className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
							{selected.slice(0, MAX_CHIPS).map((agent) => (
								<span
									key={agent.id}
									className="inline-flex min-w-0 max-w-[160px] items-center gap-1.5 rounded-full border border-hairline bg-sidebar py-0.5 pl-0.5 pr-2.5 dark:border-white/10 dark:bg-white/5"
								>
									<AgentAvatar
										agentId={agent.id}
										name={agent.name}
										imageRevision={agent.imageRevision}
										color={agent.color}
										emoji={agent.emoji}
										size="xs"
										className="size-5 text-[11px]"
									/>
									<span className="truncate text-[12px] font-semibold text-foreground">
										{agent.name}
									</span>
								</span>
							))}
							{selected.length > MAX_CHIPS && (
								<span className="rounded-full bg-petrol-tint px-2 py-0.5 text-[11px] font-semibold text-petrol dark:bg-white/10 dark:text-panel-terminal">
									+{selected.length - MAX_CHIPS}
								</span>
							)}
						</span>
					)}
					<ChevronDown
						className={cn(
							"size-4 shrink-0 text-meta transition-transform dark:text-panel-dim",
							open && "rotate-180",
						)}
					/>
				</button>
			</PopoverTrigger>
			<PopoverContent
				align="start"
				className="w-[var(--radix-popover-trigger-width)] min-w-[280px] overflow-hidden p-0"
				onOpenAutoFocus={(event) => {
					event.preventDefault();
					searchRef.current?.focus();
				}}
				onKeyDown={handleKeyboardListNavigation}
			>
				<div className="border-b border-hairline p-2 dark:border-white/10">
					<div className="relative">
						<Search className="absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-meta dark:text-panel-dim" />
						<input
							ref={searchRef}
							value={query}
							onChange={(event) => {
								setQuery(event.target.value);
							}}
							placeholder="Search agents"
							aria-label="Search agents"
							className="h-9 w-full rounded-lg border border-input bg-background pl-8 pr-2 text-[12.5px] font-medium text-foreground outline-none transition-colors placeholder:text-meta focus:border-petrol dark:placeholder:text-panel-dim"
						/>
					</div>
				</div>
				<div
					role="listbox"
					aria-multiselectable="true"
					className="max-h-[280px] overflow-y-auto p-1.5 [scrollbar-width:thin]"
				>
					{visible.map((agent) => {
						const checked = value.includes(agent.id);
						return (
							<button
								key={agent.id}
								type="button"
								role="option"
								aria-selected={checked}
								data-keyboard-option="true"
								onClick={() => {
									toggle(agent.id);
								}}
								className={cn(
									"group flex w-full cursor-pointer items-center gap-3 rounded-[9px] px-2.5 py-[9px] text-left outline-none transition-colors focus-visible:bg-hover dark:focus-visible:bg-white/5",
									checked
										? "bg-petrol-tint/60 dark:bg-white/5"
										: "hover:bg-hover dark:hover:bg-white/5",
								)}
							>
								<AgentAvatar
									agentId={agent.id}
									name={agent.name}
									imageRevision={agent.imageRevision}
									color={agent.color}
									emoji={agent.emoji}
									size="sm"
									className="transition-transform duration-200 group-hover:scale-105"
								/>
								<span className="min-w-0 flex-1">
									<span className="block truncate text-[13px] font-semibold text-foreground">
										{agent.name}
									</span>
									{(agent.description || agent.group) && (
										<span className="block truncate text-[11px] text-meta dark:text-panel-dim">
											{agent.description || agent.group}
										</span>
									)}
								</span>
								<span
									aria-hidden="true"
									className={cn(
										"flex size-[18px] shrink-0 items-center justify-center rounded-[5px] border transition-colors",
										checked
											? "border-petrol bg-petrol text-white"
											: "border-input bg-card group-hover:border-border-hover",
									)}
								>
									{checked && <Check className="size-3" strokeWidth={3} />}
								</span>
							</button>
						);
					})}
					{visible.length === 0 && (
						<p className="px-3 py-6 text-center text-[12.5px] text-meta dark:text-panel-dim">
							No agents found
						</p>
					)}
				</div>
				{visible.length > 1 && (
					<div className="flex items-center justify-between border-t border-hairline px-3 py-2 dark:border-white/10">
						<span className="text-[11.5px] text-meta dark:text-panel-dim">
							{value.length} selected
						</span>
						<button
							type="button"
							onClick={toggleVisible}
							className="cursor-pointer whitespace-nowrap text-[11.5px] font-semibold text-petrol transition-opacity hover:opacity-80 dark:text-panel-terminal"
						>
							{allVisibleSelected
								? "Clear"
								: query.trim()
									? "Select matches"
									: "Select all"}
						</button>
					</div>
				)}
			</PopoverContent>
		</Popover>
	);
}
