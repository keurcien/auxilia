"use client";

import { useState } from "react";
import { Copy, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
	Dialog,
	DialogContent,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { api } from "@/lib/api/client";

interface PersonalAccessToken {
	id: string;
	name: string;
	prefix: string;
	createdAt: string;
}

interface CreateTokenDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	onTokenCreated?: (token: PersonalAccessToken) => void;
}

export default function CreateTokenDialog({
	open,
	onOpenChange,
	onTokenCreated,
}: CreateTokenDialogProps) {
	const [name, setName] = useState("");
	const [isLoading, setIsLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [plaintext, setPlaintext] = useState<string | null>(null);
	const [copied, setCopied] = useState(false);

	const handleSubmit = async (e: React.FormEvent) => {
		e.preventDefault();
		setError(null);
		setIsLoading(true);

		try {
			const response = await api.post("/auth/tokens", { name });
			setPlaintext(response.data.token);
			onTokenCreated?.({
				id: response.data.id,
				name: response.data.name,
				prefix: response.data.prefix,
				createdAt: response.data.createdAt,
			});
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

	const handleCopy = async () => {
		if (!plaintext) return;
		await navigator.clipboard.writeText(plaintext);
		setCopied(true);
		setTimeout(() => setCopied(false), 2000);
	};

	const handleClose = (isOpen: boolean) => {
		if (!isOpen) {
			setName("");
			setError(null);
			setPlaintext(null);
			setCopied(false);
		}
		onOpenChange(isOpen);
	};

	return (
		<Dialog open={open} onOpenChange={handleClose}>
			<DialogContent className="sm:max-w-md">
				<DialogHeader>
					<DialogTitle>Create personal access token</DialogTitle>
				</DialogHeader>

				{plaintext ? (
					<div className="space-y-4">
						<p className="text-sm text-muted-foreground">
							Copy your token now. You won&apos;t be able to see it again.
						</p>
						<div className="flex items-center gap-2">
							<Input
								readOnly
								value={plaintext}
								className="text-sm font-mono"
							/>
							<Button
								type="button"
								variant="outline"
								size="icon"
								className="shrink-0 cursor-pointer"
								onClick={handleCopy}
							>
								{copied ? (
									<Check className="h-4 w-4" />
								) : (
									<Copy className="h-4 w-4" />
								)}
							</Button>
						</div>
						<Button
							className="w-full cursor-pointer"
							onClick={() => handleClose(false)}
						>
							Done
						</Button>
					</div>
				) : (
					<form onSubmit={handleSubmit} className="space-y-4">
						{error && (
							<div className="p-3 text-sm text-destructive bg-destructive/10 rounded-md">
								{error}
							</div>
						)}

						<div className="space-y-2">
							<Label htmlFor="token-name">Name</Label>
							<Input
								id="token-name"
								type="text"
								placeholder="e.g. n8n integration"
								value={name}
								onChange={(e) => setName(e.target.value)}
								required
							/>
						</div>

						<Button
							type="submit"
							className="w-full cursor-pointer"
							disabled={isLoading}
						>
							{isLoading ? "Creating..." : "Create token"}
						</Button>
					</form>
				)}
			</DialogContent>
		</Dialog>
	);
}
