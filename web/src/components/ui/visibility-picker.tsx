"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Building2, Check, ChevronDown, LockKeyhole, Search, Users } from "lucide-react";
import * as teamsApi from "@/lib/api/resources/teams";
import { cn } from "@/lib/utils";
import type { Team } from "@/types/users";
import type { ResourceVisibility } from "@/types/visibility";

interface VisibilityPickerProps {
	visibility: ResourceVisibility;
	teamIds: string[];
	onChange: (visibility: ResourceVisibility, teamIds: string[]) => void;
}

const OPTIONS = [
	{ value: "personal", label: "Personal", description: "Only you and workspace admins", Icon: LockKeyhole },
	{ value: "workspace", label: "Workspace", description: "Every workspace member", Icon: Building2 },
	{ value: "teams", label: "Teams", description: "Members of selected teams", Icon: Users },
] as const;

export function VisibilityPicker({
	visibility,
	teamIds,
	onChange,
}: VisibilityPickerProps) {
	const rootRef = useRef<HTMLDivElement>(null);
	const [open, setOpen] = useState(false);
	const [query, setQuery] = useState("");
	const [teams, setTeams] = useState<Team[]>([]);

	useEffect(() => {
		let cancelled = false;
		void teamsApi
			.listTeams()
			.then((nextTeams) => {
				if (!cancelled) setTeams(nextTeams);
			})
			.catch(() => {
				if (!cancelled) setTeams([]);
			});
		return () => {
			cancelled = true;
		};
	}, []);
	useEffect(() => {
		if (!open) return;
		const close = (event: MouseEvent) => {
			if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
		};
		document.addEventListener("mousedown", close);
		return () => {
			document.removeEventListener("mousedown", close);
		};
	}, [open]);

	const selected = OPTIONS.find((option) => option.value === visibility) ?? OPTIONS[0];
	const filtered = useMemo(() => {
		const term = query.trim().toLowerCase();
		return teams.filter((team) => !term || team.name.toLowerCase().includes(term));
	}, [query, teams]);

	const chooseVisibility = (next: ResourceVisibility) => {
		onChange(next, next === "teams" ? teamIds : []);
		if (next !== "teams") setOpen(false);
	};

	return (
		<div ref={rootRef} className="relative">
			<label className="mb-1.5 block text-[11px] font-semibold text-label dark:text-muted-foreground">
				Visibility
			</label>
			<button
				type="button"
				aria-haspopup="listbox"
				aria-expanded={open}
				onClick={() => {
					setOpen((current) => !current);
				}}
				className="flex h-9 w-full cursor-pointer items-center gap-2 rounded-lg border border-input bg-card px-3 text-left"
			>
				<selected.Icon className="size-4 text-meta" />
				<span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-foreground">
					{selected.label}
				</span>
				<ChevronDown className={cn("size-3.5 text-meta transition-transform", open && "rotate-180")} />
			</button>

			{open && (
				<div className="absolute left-0 right-0 top-full z-50 mt-1 overflow-hidden rounded-xl border border-border bg-card shadow-[0_14px_40px_rgba(16,24,32,0.14)] dark:border-white/10">
					<div className="p-1.5">
						{OPTIONS.map(({ value, label, description, Icon }) => (
							<button
								key={value}
								type="button"
								onClick={() => {
									chooseVisibility(value);
								}}
								className="flex w-full cursor-pointer items-center gap-2.5 rounded-lg px-3 py-2 text-left hover:bg-sidebar dark:hover:bg-white/5"
							>
								<Icon className="size-4 text-meta" />
								<span className="min-w-0 flex-1">
									<span className="block text-[12.5px] font-semibold text-foreground">{label}</span>
									<span className="block text-[10.5px] text-meta">{description}</span>
								</span>
								{visibility === value && <Check className="size-3.5 text-petrol" />}
							</button>
						))}
					</div>
					{visibility === "teams" && (
						<div className="border-t border-border p-2 dark:border-white/10">
							<div className="relative mb-1.5">
								<Search className="absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-meta" />
								<input
									value={query}
									onChange={(event) => {
										setQuery(event.target.value);
									}}
									placeholder="Search teams…"
									className="h-8 w-full rounded-lg border border-input bg-background pl-8 pr-2 text-[12px] outline-none focus:border-petrol"
								/>
							</div>
							<div className="max-h-44 overflow-y-auto">
								{filtered.map((team) => {
									const checked = teamIds.includes(team.id);
									return (
										<button
											key={team.id}
											type="button"
											onClick={() => {
												onChange(
													"teams",
													checked
														? teamIds.filter((id) => id !== team.id)
														: [...teamIds, team.id],
												);
											}}
											className="flex w-full cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[12.5px] hover:bg-sidebar dark:hover:bg-white/5"
										>
											<span
												className="size-2.5 rounded-full"
												style={{ backgroundColor: team.color ?? "#78909C" }}
											/>
											<span className="min-w-0 flex-1 truncate">{team.name}</span>
											{checked && <Check className="size-3.5 text-petrol" />}
										</button>
									);
								})}
								{filtered.length === 0 && (
									<p className="px-3 py-4 text-center text-[12px] text-meta">No teams found</p>
								)}
							</div>
						</div>
					)}
				</div>
			)}
			{visibility === "teams" && teamIds.length === 0 && (
				<p className="mt-1.5 text-[11px] text-destructive">Select at least one team.</p>
			)}
		</div>
	);
}
