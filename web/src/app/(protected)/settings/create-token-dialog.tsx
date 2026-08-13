"use client";

import { useState } from "react";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogTitle,
} from "@/components/ui/dialog";
import { api } from "@/lib/api/client";

export interface PersonalAccessToken {
	id: string;
	name: string;
	prefix: string;
	createdAt: string;
}

interface CreateTokenDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	/** Fires once on success with the one-time plaintext — the page shows the
	 * reveal banner (design 18a); the dialog closes immediately. */
	onTokenCreated?: (token: PersonalAccessToken, plaintext: string) => void;
}

export default function CreateTokenDialog({
	open,
	onOpenChange,
	onTokenCreated,
}: CreateTokenDialogProps) {
	const [name, setName] = useState("");
	const [isLoading, setIsLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);

	const handleSubmit = async (e: React.FormEvent) => {
		e.preventDefault();
		setError(null);
		setIsLoading(true);

		try {
			const response = await api.post("/auth/tokens", { name });
			onTokenCreated?.(
				{
					id: response.data.id,
					name: response.data.name,
					prefix: response.data.prefix,
					createdAt: response.data.createdAt,
				},
				response.data.token,
			);
			handleClose(false);
		} catch (err: unknown) {
			if (err && typeof err === "object" && "response" in err) {
				const axiosError = err as {
					response?: { data?: { detail?: string } };
				};
				setError(axiosError.response?.data?.detail || "An error occurred");
			} else {
				setError("An error occurred");
			}
		} finally {
			setIsLoading(false);
		}
	};

	const handleClose = (isOpen: boolean) => {
		if (!isOpen) {
			setName("");
			setError(null);
		}
		onOpenChange(isOpen);
	};

	return (
		<Dialog open={open} onOpenChange={handleClose}>
			<DialogContent className="sm:max-w-[420px]">
				<DialogTitle className="font-display text-[20px] font-bold tracking-[-0.025em] text-foreground">
					Generate a token
				</DialogTitle>
				<DialogDescription className="text-[13px] leading-[1.55] text-subtle dark:text-panel-body">
					The token acts as you. You&apos;ll see it once — store it in the
					service that needs it.
				</DialogDescription>

				<form
					onSubmit={(e) => {
						void handleSubmit(e);
					}}
					className="flex flex-col gap-4"
				>
					{error && (
						<div className="rounded-[10px] bg-destructive/10 px-3.5 py-2.5 text-[13px] font-medium text-destructive">
							{error}
						</div>
					)}

					<div className="flex flex-col gap-[7px]">
						<label
							htmlFor="token-name"
							className="font-mono text-[10.5px] font-semibold tracking-[0.09em] text-label dark:text-panel-dim"
						>
							NAME
						</label>
						<input
							id="token-name"
							type="text"
							placeholder="e.g. n8n integration"
							value={name}
							onChange={(e) => {
								setName(e.target.value);
							}}
							required
							className="w-full rounded-lg border border-input bg-card px-3 py-[9px] text-[13.5px] font-medium text-foreground outline-none transition-[border-color,box-shadow] placeholder:text-meta dark:placeholder:text-panel-dim focus:border-petrol focus:shadow-[0_0_0_3px_rgba(22,96,110,0.10)]"
						/>
					</div>

					<button
						type="submit"
						disabled={isLoading || !name.trim()}
						className="cursor-pointer rounded-[7px] bg-petrol px-[18px] py-2.5 text-[13.5px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
					>
						{isLoading ? "Creating…" : "Create token"}
					</button>
				</form>
			</DialogContent>
		</Dialog>
	);
}
