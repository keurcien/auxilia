"use client";

import { useState } from "react";
import {
	Dialog,
	DialogButton,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { AGENT_COLORS } from "@/lib/colors";
import * as teamsApi from "@/lib/api/resources/teams";
import { getApiErrorMessage } from "@/lib/api/errors";
import type { Team } from "@/types/users";

export type { Team };

interface NewTeamDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	team?: Team | null;
	onTeamCreated?: (team: Team) => void;
	onTeamUpdated?: (team: Team) => void;
}

export default function NewTeamDialog({
	open,
	onOpenChange,
	team,
	onTeamCreated,
	onTeamUpdated,
}: NewTeamDialogProps) {
	const isEdit = !!team;
	const [name, setName] = useState(team?.name ?? "");
	const [color, setColor] = useState<string>(
		team?.color ?? AGENT_COLORS[0],
	);
	const [isSubmitting, setIsSubmitting] = useState(false);
	const [error, setError] = useState<string | null>(null);

	const handleSubmit = async (e: React.FormEvent) => {
		e.preventDefault();
		const trimmed = name.trim();
		if (!trimmed) return;
		setError(null);
		setIsSubmitting(true);
		try {
			if (team) {
				onTeamUpdated?.(await teamsApi.updateTeam(team.id, { name: trimmed, color }));
			} else {
				onTeamCreated?.(await teamsApi.createTeam({ name: trimmed, color }));
			}
			onOpenChange(false);
		} catch (err: unknown) {
			setError(getApiErrorMessage(err, "An error occurred"));
		} finally {
			setIsSubmitting(false);
		}
	};

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="sm:max-w-[560px]">
				<DialogHeader>
					<DialogTitle>{isEdit ? "Edit team" : "New team"}</DialogTitle>
					<DialogDescription>
						Group members so they share a set of agents
					</DialogDescription>
				</DialogHeader>

				<form
					onSubmit={(e) => {
						void handleSubmit(e);
					}}
					className="flex flex-col gap-5"
				>
					{error && (
						<div className="rounded-[10px] bg-[#FBEFED] px-3.5 py-2.5 text-[13px] font-medium text-[#B04A3A] dark:bg-[#B04A3A]/10">
							{error}
						</div>
					)}

					<div className="flex flex-col gap-[7px]">
						<label
							htmlFor="team-name"
							className="text-[13px] font-semibold text-ink dark:text-panel-button"
						>
							Name
						</label>
						<input
							id="team-name"
							type="text"
							autoFocus
							placeholder="e.g. Marketing"
							value={name}
							onChange={(e) => {
								setName(e.target.value);
							}}
							className="w-full rounded-lg border border-input bg-card px-3 py-[9px] text-[13.5px] font-medium text-foreground outline-none transition-[border-color,box-shadow] placeholder:text-meta dark:placeholder:text-panel-dim focus:border-petrol focus:shadow-[0_0_0_3px_rgba(22,96,110,0.10)]"
						/>
					</div>

					<div className="flex flex-col gap-2.5">
						<span className="text-[13px] font-semibold text-ink dark:text-panel-button">
							Color
						</span>
						<div className="flex items-center gap-2.5">
							{AGENT_COLORS.map((c) => (
								<button
									key={c}
									type="button"
									aria-label={`Color ${c}`}
									aria-pressed={color === c}
									title={c}
									onClick={() => {
										setColor(c);
									}}
									style={{ backgroundColor: c }}
									className={`size-7 cursor-pointer rounded-full transition-transform hover:scale-110 ${
										color === c
											? "ring-2 ring-petrol ring-offset-2 dark:ring-offset-card"
											: ""
									}`}
								/>
							))}
							<label
								title="Custom color"
								className={`relative size-7 cursor-pointer overflow-hidden rounded-full bg-[conic-gradient(#e84393,#e17055,#fdcb6e,#00b894,#0984e3,#6c5ce7,#e84393)] transition-transform hover:scale-110 ${
									!AGENT_COLORS.includes(color)
										? "ring-2 ring-petrol ring-offset-2 dark:ring-offset-card"
										: ""
								}`}
							>
								<span className="absolute inset-[5px] rounded-full border border-white/80 bg-card" />
								<input
									type="color"
									value={color}
									aria-label="Custom team color"
									onChange={(event) => {
										setColor(event.target.value.toUpperCase());
									}}
									className="absolute inset-0 size-full cursor-pointer opacity-0"
								/>
							</label>
						</div>
					</div>

					<DialogFooter>
						<DialogButton
							variant="outline"
							onClick={() => {
								onOpenChange(false);
							}}
						>
							Cancel
						</DialogButton>
						<DialogButton type="submit" disabled={isSubmitting || !name.trim()}>
							{isSubmitting ? "Saving…" : isEdit ? "Save" : "Create team"}
						</DialogButton>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
