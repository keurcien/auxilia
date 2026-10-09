"use client";

import * as DropdownMenuPrimitive from "@radix-ui/react-dropdown-menu";
import { useEffect, useMemo, useState } from "react";
import {
	Building2,
	Check,
	ChevronDown,
	Layers3,
	LockKeyhole,
	Search,
	Users,
} from "lucide-react";
import * as teamsApi from "@/lib/api/resources/teams";
import type { ResourceScopeFilter } from "@/lib/resource-scope-filter";
import { cn } from "@/lib/utils";
import type { Team } from "@/types/users";

interface ResourceScopeFilterProps {
	value: ResourceScopeFilter;
	teamIds: string[];
	onChange: (value: ResourceScopeFilter, teamIds: string[]) => void;
}

const VISIBILITY_OPTIONS = [
	{
		value: "personal",
		label: "Personal",
		description: "Only owners and workspace admins",
		Icon: LockKeyhole,
	},
	{
		value: "workspace",
		label: "Workspace",
		description: "Visible to every workspace member",
		Icon: Building2,
	},
	{
		value: "teams",
		label: "Teams",
		description: "Visible to selected teams",
		Icon: Users,
	},
] as const;

export function ResourceScopeFilterDropdown({
	value,
	teamIds,
	onChange,
}: ResourceScopeFilterProps) {
	const [open, setOpen] = useState(false);
	const [query, setQuery] = useState("");
	const [teams, setTeams] = useState<Team[]>([]);

	useEffect(() => {
		void teamsApi
			.listTeams()
			.then(setTeams)
			.catch(() => {
				setTeams([]);
			});
	}, []);

	const selected =
		value === "all"
			? { label: "All", Icon: Layers3 }
			: (VISIBILITY_OPTIONS.find((option) => option.value === value) ??
				VISIBILITY_OPTIONS[1]);

	const filteredTeams = useMemo(() => {
		const term = query.trim().toLowerCase();
		return teams.filter(
			(team) => !term || team.name.toLowerCase().includes(term),
		);
	}, [query, teams]);

	const choose = (next: ResourceScopeFilter) => {
		onChange(next, next === "teams" ? teamIds : []);
		if (next !== "teams") setOpen(false);
	};

	return (
		<DropdownMenuPrimitive.Root open={open} onOpenChange={setOpen}>
			<DropdownMenuPrimitive.Trigger asChild>
				<button
					type="button"
					className="flex h-8 shrink-0 cursor-pointer items-center gap-2 whitespace-nowrap rounded-[7px] border border-border bg-card px-2.5 text-[12.5px] font-medium text-foreground"
				>
					<selected.Icon className="size-3.5 text-meta" />
					<span>{selected.label}</span>
					<ChevronDown
						className={cn(
							"size-3.5 text-meta transition-transform",
							open && "rotate-180",
						)}
					/>
				</button>
			</DropdownMenuPrimitive.Trigger>

			<DropdownMenuPrimitive.Portal>
				<DropdownMenuPrimitive.Content
					align="start"
					sideOffset={4}
					collisionPadding={16}
					className="z-50 max-h-[min(70dvh,36rem)] w-[min(300px,calc(100vw-2rem))] overflow-y-auto rounded-[7px] border border-border bg-card shadow-[0_14px_40px_rgba(16,24,32,0.14)] dark:border-white/10"
				>
					<div className="p-1.5">
						<p className="px-3 pb-1 pt-1 text-[9.5px] font-semibold uppercase tracking-[0.08em] text-meta">
							Visibility
						</p>
						<button
							type="button"
							onClick={() => {
								choose("all");
							}}
							className="flex w-full cursor-pointer items-center gap-2.5 rounded-[5px] px-3 py-2 text-left hover:bg-sidebar dark:hover:bg-white/5"
						>
							<Layers3 className="size-4 shrink-0 text-meta" />
							<span className="min-w-0 flex-1">
								<span className="block text-[12.5px] font-semibold text-foreground">
									All
								</span>
								<span className="block text-[10.5px] text-meta">
									Every visibility
								</span>
							</span>
							{value === "all" && (
								<Check className="size-3.5 shrink-0 text-petrol" />
							)}
						</button>
						{VISIBILITY_OPTIONS.map(
							({ value: optionValue, label, description, Icon }) => (
								<button
									key={optionValue}
									type="button"
									onClick={() => {
										choose(optionValue);
									}}
									className="flex w-full cursor-pointer items-center gap-2.5 rounded-[5px] px-3 py-2 text-left hover:bg-sidebar dark:hover:bg-white/5"
								>
									<Icon className="size-4 shrink-0 text-meta" />
									<span className="min-w-0 flex-1">
										<span className="block text-[12.5px] font-semibold text-foreground">
											{label}
										</span>
										<span className="block text-[10.5px] text-meta">
											{description}
										</span>
									</span>
									{value === optionValue && (
										<Check className="size-3.5 shrink-0 text-petrol" />
									)}
								</button>
							),
						)}
					</div>

					{value === "teams" && (
						<div className="border-t border-border p-2 dark:border-white/10">
							<div className="relative mb-1.5">
								<Search className="absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-meta" />
								<input
									value={query}
									onChange={(event) => {
										setQuery(event.target.value);
									}}
									onKeyDown={(event) => {
										event.stopPropagation();
									}}
									placeholder="Search teams…"
									className="h-8 w-full rounded-[5px] border border-input bg-background pl-8 pr-2 text-[12px] outline-none focus:border-petrol"
								/>
							</div>
							<div className="max-h-44 overflow-y-auto">
								{filteredTeams.map((team) => {
									const checked = teamIds.includes(team.id);
									return (
										<button
											key={team.id}
											type="button"
											onClick={() => {
												onChange(
													"teams",
													checked
														? teamIds.filter((teamId) => teamId !== team.id)
														: [...teamIds, team.id],
												);
											}}
											className="flex w-full cursor-pointer items-center gap-2 rounded-[5px] px-2.5 py-2 text-left text-[12.5px] hover:bg-sidebar dark:hover:bg-white/5"
										>
											<span
												className="size-2.5 shrink-0 rounded-full"
												style={{ backgroundColor: team.color ?? "#78909C" }}
											/>
											<span className="min-w-0 flex-1 truncate">
												{team.name}
											</span>
											{checked && (
												<Check className="size-3.5 shrink-0 text-petrol" />
											)}
										</button>
									);
								})}
								{filteredTeams.length === 0 && (
									<p className="px-3 py-4 text-center text-[12px] text-meta">
										No teams found
									</p>
								)}
							</div>
						</div>
					)}
				</DropdownMenuPrimitive.Content>
			</DropdownMenuPrimitive.Portal>
		</DropdownMenuPrimitive.Root>
	);
}
