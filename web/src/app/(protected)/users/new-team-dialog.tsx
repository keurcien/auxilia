"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { SageInput } from "@/components/ui/sage-input";
import { SageButton } from "@/components/ui/sage-button";
import { AGENT_COLORS } from "@/lib/colors";
import { api } from "@/lib/api/client";

export interface Team {
	id: string;
	name: string;
	color: string | null;
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
			<DialogContent
				className="sm:max-w-[460px] rounded-[28px] p-0 gap-0 overflow-hidden"
				showCloseButton={false}
			>
				<form
					onSubmit={(e) => {
						void handleSubmit(e);
					}}
				>
					{/* Header */}
					<div className="flex items-start justify-between px-8 pt-7 pb-0">
						<div>
							<DialogTitle className="font-[family-name:var(--font-jakarta-sans)] text-[22px] font-extrabold text-[#111111] dark:text-white tracking-[-0.02em]">
								{isEdit ? "Edit team" : "New team"}
							</DialogTitle>
							<p className="font-[family-name:var(--font-dm-sans)] text-[14px] text-[#8FA89E] dark:text-muted-foreground font-medium mt-1">
								Group members so they share a set of agents
							</p>
						</div>
						<button
							type="button"
							onClick={() => {
								onOpenChange(false);
							}}
							className="shrink-0 flex items-center justify-center w-9 h-9 rounded-full bg-[#F5F8F6] dark:bg-white/10 text-[#6B7F76] hover:bg-[#EDF4F0] dark:hover:bg-white/15 transition-colors cursor-pointer"
						>
							<X className="w-4 h-4" />
						</button>
					</div>

					{/* Content */}
					<div className="px-8 pt-6 pb-2">
						{error && (
							<div className="mb-5 p-3.5 rounded-2xl bg-red-50 dark:bg-red-950/30 text-[13px] font-medium text-red-600 dark:text-red-400 font-[family-name:var(--font-dm-sans)]">
								{error}
							</div>
						)}

						<label
							htmlFor="team-name"
							className="block font-[family-name:var(--font-dm-sans)] text-[13px] font-semibold text-[#1E2D28] dark:text-foreground mb-2"
						>
							Name
						</label>
						<SageInput
							id="team-name"
							autoFocus
							placeholder="e.g. Marketing"
							value={name}
							onChange={(e) => {
								setName(e.target.value);
							}}
						/>

						<label className="block font-[family-name:var(--font-dm-sans)] text-[13px] font-semibold text-[#1E2D28] dark:text-foreground mt-5 mb-2.5">
							Color
						</label>
						<div className="flex items-center gap-2.5">
							{AGENT_COLORS.map((c) => (
								<button
									key={c}
									type="button"
									onClick={() => {
										setColor(c);
									}}
									style={{ backgroundColor: c }}
									className={`w-7 h-7 rounded-full cursor-pointer transition-transform hover:scale-110 ${
										color === c
											? "ring-2 ring-offset-2 ring-gray-400 dark:ring-offset-[#222]"
											: ""
									}`}
								/>
							))}
						</div>
					</div>

					{/* Footer */}
					<div className="flex items-center justify-end gap-2.5 px-8 pt-5 pb-6 mt-4 border-t border-[#F0F3F2] dark:border-white/5">
						<SageButton
							type="button"
							color="outline"
							onClick={() => {
								onOpenChange(false);
							}}
						>
							Cancel
						</SageButton>
						<SageButton type="submit" disabled={isSubmitting || !name.trim()}>
							{isSubmitting
								? "Saving..."
								: isEdit
									? "Save"
									: "Create team"}
						</SageButton>
					</div>
				</form>
			</DialogContent>
		</Dialog>
	);
}
