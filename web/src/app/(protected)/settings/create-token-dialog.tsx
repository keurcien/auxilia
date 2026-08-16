"use client";

import { useState } from "react";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
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
			<DialogContent className="sm:max-w-[560px]">
				<DialogHeader>
					<DialogTitle>Generate a token</DialogTitle>
					<DialogDescription>
						The token acts as you. You&apos;ll see it once — store it in the
						service that needs it.
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
							htmlFor="token-name"
							className="text-[13px] font-semibold text-ink dark:text-panel-button"
						>
							Name
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

					<DialogFooter>
						<button
							type="button"
							onClick={() => {
								handleClose(false);
							}}
							className="cursor-pointer rounded-[7px] border border-input px-[18px] py-2 text-[13px] font-semibold text-ink transition-colors hover:border-border-hover dark:text-panel-button dark:hover:border-white/30"
						>
							Cancel
						</button>
						<button
							type="submit"
							disabled={isLoading || !name.trim()}
							className="cursor-pointer rounded-[7px] bg-petrol px-[18px] py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
						>
							{isLoading ? "Creating…" : "Create token"}
						</button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
