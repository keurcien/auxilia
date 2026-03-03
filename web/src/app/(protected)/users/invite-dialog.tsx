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
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { api } from "@/lib/api/client";

type Role = "member" | "editor" | "admin";

interface Invite {
	id: string;
	email: string;
	role: string;
	inviteUrl: string;
	invitedByName: string | null;
	createdAt: string;
}

interface InviteDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	onInviteCreated?: (invite: Invite) => void;
}

export default function InviteDialog({ open, onOpenChange, onInviteCreated }: InviteDialogProps) {
	const [email, setEmail] = useState("");
	const [role, setRole] = useState<Role>("member");
	const [isLoading, setIsLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [inviteUrl, setInviteUrl] = useState<string | null>(null);
	const [copied, setCopied] = useState(false);

	const handleSubmit = async (e: React.FormEvent) => {
		e.preventDefault();
		setError(null);
		setIsLoading(true);

		try {
			const response = await api.post("/invites/", { email, role });
			setInviteUrl(response.data.inviteUrl);
			onInviteCreated?.(response.data);
		} catch (err: unknown) {
			if (err && typeof err === "object" && "response" in err) {
				const axiosError = err as { response?: { data?: { detail?: string } } };
				setError(axiosError.response?.data?.detail || "An error occurred");
			} else {
				setError("An error occurred");
			}
		} finally {
			setIsLoading(false);
		}
	};

	const handleCopy = async () => {
		if (!inviteUrl) return;
		await navigator.clipboard.writeText(inviteUrl);
		setCopied(true);
		setTimeout(() => setCopied(false), 2000);
	};

	const handleClose = (isOpen: boolean) => {
		if (!isOpen) {
			setEmail("");
			setRole("member");
			setError(null);
			setInviteUrl(null);
			setCopied(false);
		}
		onOpenChange(isOpen);
	};

	return (
		<Dialog open={open} onOpenChange={handleClose}>
			<DialogContent className="sm:max-w-md">
				<DialogHeader>
					<DialogTitle>Invite a member</DialogTitle>
				</DialogHeader>

				{inviteUrl ? (
					<div className="space-y-4">
						<p className="text-sm text-muted-foreground">
							Share this link with <span className="font-medium text-foreground">{email}</span> to invite them to the workspace.
						</p>
						<div className="flex items-center gap-2">
							<Input
								readOnly
								value={inviteUrl}
								className="text-sm"
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
							<Label htmlFor="invite-email">Email</Label>
							<Input
								id="invite-email"
								type="email"
								placeholder="colleague@example.com"
								value={email}
								onChange={(e) => setEmail(e.target.value)}
								required
							/>
						</div>

						<div className="space-y-2">
							<Label htmlFor="invite-role">Role</Label>
							<Select value={role} onValueChange={(v: Role) => setRole(v)}>
								<SelectTrigger>
									<SelectValue />
								</SelectTrigger>
								<SelectContent>
									<SelectItem value="member">Member</SelectItem>
									<SelectItem value="editor">Editor</SelectItem>
									<SelectItem value="admin">Admin</SelectItem>
								</SelectContent>
							</Select>
						</div>

						<Button
							type="submit"
							className="w-full cursor-pointer"
							disabled={isLoading}
						>
							{isLoading ? "Creating invite..." : "Create invite"}
						</Button>
					</form>
				)}
			</DialogContent>
		</Dialog>
	);
}
