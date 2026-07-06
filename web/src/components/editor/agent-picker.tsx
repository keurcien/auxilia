"use client";

import { useEffect, useState } from "react";
import { CheckIcon, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAgentsStore } from "@/stores/agents-store";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import { SearchBar } from "@/components/ui/search-bar";
import {
	Dialog,
	DialogContent,
	DialogTitle,
	DialogTrigger,
} from "@/components/ui/dialog";

interface AgentPickerProps {
	value: string | null;
	onChange: (agentId: string) => void;
	/** Read-only row: no dialog, no chevron. */
	disabled?: boolean;
}

/**
 * Picks among the agents the current user can use — same searchable
 * dialog as the chat's agent selector.
 */
export function AgentPicker({ value, onChange, disabled }: AgentPickerProps) {
	const agents = useAgentsStore((state) => state.agents);
	const fetchAgents = useAgentsStore((state) => state.fetchAgents);
	const [open, setOpen] = useState(false);
	const [search, setSearch] = useState("");

	useEffect(() => {
		fetchAgents().catch(() => {
			// surfaced by the store; the picker just shows an empty list
		});
	}, [fetchAgents]);

	const selectableAgents = agents
		.filter((agent) => agent.currentUserPermission != null && !agent.isArchived)
		.filter((agent) =>
			agent.name.toLowerCase().includes(search.trim().toLowerCase()),
		);
	const selected = agents.find((agent) => agent.id === value);

	const handleOpenChange = (nextOpen: boolean) => {
		setOpen(nextOpen);
		if (!nextOpen) setSearch("");
	};

	const row = (
		<div
			className={cn(
				"flex w-full items-center justify-between h-14 px-4 rounded-[14px] border border-[#e1ebe6] dark:border-white/10 bg-white dark:bg-card shadow-[0_1px_3px_rgba(33,36,31,0.04)] transition-colors",
				!disabled && "cursor-pointer hover:border-[#A3B5AD]",
			)}
		>
			{selected ? (
				<div className="flex items-center gap-2.5 min-w-0">
					<AgentAvatar
						color={selected.color}
						emoji={selected.emoji}
						size="xs"
					/>
					<span className="font-[family-name:var(--font-dm-sans)] text-[14px] font-semibold text-[#1E2D28] dark:text-white truncate">
						{selected.name}
					</span>
				</div>
			) : (
				<span className="font-[family-name:var(--font-dm-sans)] text-[14px] font-medium text-[#A3B5AD] dark:text-white/30">
					Select an agent
				</span>
			)}
			{!disabled && (
				<ChevronDown className="size-[18px] shrink-0 text-[#9AA8A1]" />
			)}
		</div>
	);

	if (disabled) {
		return row;
	}

	return (
		<Dialog open={open} onOpenChange={handleOpenChange}>
			<DialogTrigger asChild>
				<button type="button" className="w-full text-left">
					{row}
				</button>
			</DialogTrigger>
			<DialogContent
				className="sm:max-w-[440px] rounded-[28px] p-0 gap-0 overflow-hidden"
				showCloseButton={false}
			>
				{/* Header */}
				<div className="px-8 pt-7 pb-0">
					<DialogTitle className="font-[family-name:var(--font-jakarta-sans)] text-[22px] font-extrabold text-[#111111] dark:text-white tracking-[-0.02em]">
						Select an agent
					</DialogTitle>
					<p className="font-[family-name:var(--font-dm-sans)] text-[14px] text-[#8FA89E] dark:text-muted-foreground font-medium mt-2 leading-relaxed">
						Runs execute with this agent&apos;s tools
					</p>
				</div>

				{/* Search */}
				<div className="px-8 pt-5 pb-1">
					<SearchBar
						placeholder="Search for an agent..."
						value={search}
						onChange={setSearch}
					/>
				</div>

				{/* Agent list */}
				<div className="px-5 pt-3 pb-6 max-h-[340px] overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
					{selectableAgents.map((agent) => {
						const isActive = agent.id === value;
						return (
							<div
								key={agent.id}
								className={cn(
									"flex items-center gap-3.5 px-3 py-2.5 rounded-[16px] cursor-pointer transition-all duration-200 group",
									isActive
										? "bg-[#F8FAF9] dark:bg-white/5"
										: "hover:bg-[#F8FAF9] dark:hover:bg-white/5",
								)}
								onClick={() => {
									onChange(agent.id);
									handleOpenChange(false);
								}}
							>
								<AgentAvatar
									color={agent.color}
									emoji={agent.emoji}
									size="md"
									className="transition-transform duration-300 group-hover:scale-105"
								/>
								<span className="flex-1 font-[family-name:var(--font-dm-sans)] text-[14.5px] font-semibold text-[#1E2D28] dark:text-foreground truncate">
									{agent.name}
								</span>
								{isActive && (
									<CheckIcon
										className="ml-auto size-4 shrink-0 text-[#4CA882]"
										strokeWidth={3}
									/>
								)}
							</div>
						);
					})}
					{selectableAgents.length === 0 && (
						<p className="font-[family-name:var(--font-dm-sans)] text-center text-[14px] text-[#A3B5AD] dark:text-muted-foreground font-medium py-8">
							No agents found.
						</p>
					)}
				</div>
			</DialogContent>
		</Dialog>
	);
}
