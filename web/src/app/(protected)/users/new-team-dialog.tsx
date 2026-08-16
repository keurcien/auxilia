"use client";

import { useEffect, useState } from "react";
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
import { api } from "@/lib/api/client";

export interface Team {
	id: string;
	name: string;
	color: string | null;
	/** Only meaningful on the list endpoint; create/update responses report 0. */
	memberCount: number;
}

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
	const [name, setName] = useState("");
	const [color, setColor] = useState<string>(AGENT_COLORS[0]);
	const [isSubmitting, setIsSubmitting] = useState(false);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		if (open) {
			setName(team?.name ?? "");
			setColor(team?.color ?? AGENT_COLORS[0]);
			setError(null);
			setIsSubmitting(false);
		}
	}, [open, team]);

	const handleSubmit = async (e: React.FormEvent) => {
		e.preventDefault();
		const trimmed = name.trim();
		if (!trimmed) return;
		setError(null);
		setIsSubmitting(true);
		try {
			if (team) {
				const response = await api.patch(`/teams/${team.id}`, {
					name: trimmed,
					color,
				});
				onTeamUpdated?.(response.data as Team);
			} else {
				const response = await api.post("/teams/", { name: trimmed, color });
				onTeamCreated?.(response.data as Team);
			}
			onOpenChange(false);
		} catch (err: unknown) {
			if (err && typeof err === "object" && "response" in err) {
				const axiosError = err as { response?: { data?: { detail?: string } } };
				setError(axiosError.response?.data?.detail || "An error occurred");
			} else {
				setError("An error occurred");
			}
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
