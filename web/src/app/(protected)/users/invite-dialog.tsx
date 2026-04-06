"use client";

import { useState } from "react";
import { Copy, Check, X } from "lucide-react";
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

export default function InviteDialog({
	open,
	onOpenChange,
	onInviteCreated,
}: InviteDialogProps) {
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
		if (!inviteUrl) return;
		await navigator.clipboard.writeText(inviteUrl);
		setCopied(true);
		setTimeout(() => setCopied(false), 2000);
	};

	const handleClose = () => {
		setEmail("");
		setRole("member");
		setError(null);
		setInviteUrl(null);
		setCopied(false);
		onOpenChange(false);
	};

	if (!open) return null;

	return (
		<div
			className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(30,45,40,0.2)] backdrop-blur-[4px] animate-in fade-in duration-200"
			onClick={handleClose}
		>
			<div
				className="bg-white dark:bg-card rounded-[28px] p-8 w-[420px] max-w-[90vw] shadow-[0_24px_48px_-12px_rgba(0,0,0,0.12)] animate-in slide-in-from-bottom-4 zoom-in-[0.97] duration-300"
				onClick={(e) => e.stopPropagation()}
			>
				{/* Header */}
				<div className="flex items-center justify-between mb-7">
					<h2 className="font-[family-name:var(--font-jakarta-sans)] text-[20px] font-extrabold text-[#111111] dark:text-white tracking-[-0.02em]">
						Invite a member
					</h2>
					<button
						onClick={handleClose}
						className="w-9 h-9 rounded-full bg-[#F5F8F6] dark:bg-white/10 flex items-center justify-center cursor-pointer transition-colors hover:bg-[#EDF4F0] dark:hover:bg-white/15"
					>
						<X className="h-4 w-4 text-[#6B7F76]" />
					</button>
				</div>

				{inviteUrl ? (
					<div className="space-y-5">
						<p className="font-[family-name:var(--font-dm-sans)] text-[14px] text-[#6B7F76] dark:text-muted-foreground">
							Share this link with{" "}
							<span className="font-semibold text-[#1E2D28] dark:text-foreground">
								{email}
							</span>{" "}
							to invite them to the workspace.
						</p>
						<div className="flex items-center gap-2.5">
							<input
								readOnly
								value={inviteUrl}
								className="flex-1 min-w-0 px-4.5 py-3 rounded-full border-[1.5px] border-[#E0E8E4] dark:border-white/10 bg-[#FAFCFB] dark:bg-white/5 font-[family-name:var(--font-dm-sans)] text-[14px] font-medium text-[#1E2D28] dark:text-white truncate focus:outline-none"
							/>
							<button
								onClick={handleCopy}
								className={`shrink-0 flex items-center gap-1.5 px-4 py-3 rounded-full border-[1.5px] font-[family-name:var(--font-dm-sans)] text-[13px] font-semibold cursor-pointer transition-all duration-200 ${
									copied
										? "bg-[#EDF4F0] dark:bg-white/10 text-[#3D8B63] dark:text-emerald-400 border-[#3D8B63]/20"
										: "bg-white dark:bg-transparent text-[#6B7F76] dark:text-muted-foreground border-[#E0E8E4] dark:border-white/10 hover:border-[#A3B5AD]"
								}`}
							>
								{copied ? (
									<Check className="h-3.5 w-3.5" />
								) : (
									<Copy className="h-3.5 w-3.5" />
								)}
								{copied ? "Copied!" : "Copy"}
							</button>
						</div>
						<button
							onClick={handleClose}
							className="w-full py-3.5 rounded-full bg-[#111111] dark:bg-white text-white dark:text-[#111111] font-[family-name:var(--font-dm-sans)] text-[15px] font-semibold cursor-pointer shadow-[0_4px_12px_-2px_rgba(0,0,0,0.15)] transition-all hover:opacity-90"
						>
							Done
						</button>
					</div>
				) : (
					<form onSubmit={handleSubmit}>
						{error && (
							<div className="mb-5 p-3.5 rounded-2xl bg-red-50 dark:bg-red-950/30 text-[13px] font-medium text-red-600 dark:text-red-400 font-[family-name:var(--font-dm-sans)]">
								{error}
							</div>
						)}

						{/* Email */}
						<div className="mb-5">
							<label className="block font-[family-name:var(--font-dm-sans)] text-[13px] font-semibold text-[#1E2D28] dark:text-foreground mb-2">
								Email
							</label>
							<input
								type="email"
								placeholder="colleague@example.com"
								value={email}
								onChange={(e) => setEmail(e.target.value)}
								required
								className="w-full px-4.5 py-3 rounded-full border-[1.5px] border-[#E0E8E4] dark:border-white/10 bg-[#FAFCFB] dark:bg-white/5 font-[family-name:var(--font-dm-sans)] text-[14px] font-medium text-[#1E2D28] dark:text-white placeholder:text-[#A3B5AD] dark:placeholder:text-white/30 focus:outline-none focus:border-[#4CA882] transition-colors"
							/>
						</div>

						{/* Role */}
						<div className="mb-7">
							<label className="block font-[family-name:var(--font-dm-sans)] text-[13px] font-semibold text-[#1E2D28] dark:text-foreground mb-2">
								Role
							</label>
							<select
								value={role}
								onChange={(e) => setRole(e.target.value as Role)}
								className="w-auto px-4.5 py-3 pr-9 rounded-full border-[1.5px] border-[#E0E8E4] dark:border-white/10 bg-[#FAFCFB] dark:bg-white/5 font-[family-name:var(--font-dm-sans)] text-[14px] font-semibold text-[#1E2D28] dark:text-white cursor-pointer appearance-none focus:outline-none focus:border-[#4CA882] transition-colors bg-[url('data:image/svg+xml,%3Csvg%20width%3D%2712%27%20height%3D%2712%27%20viewBox%3D%270%200%2024%2024%27%20fill%3D%27none%27%20stroke%3D%27%238FA89E%27%20stroke-width%3D%272%27%20stroke-linecap%3D%27round%27%20stroke-linejoin%3D%27round%27%20xmlns%3D%27http%3A//www.w3.org/2000/svg%27%3E%3Cpolyline%20points%3D%276%209%2012%2015%2018%209%27/%3E%3C/svg%3E')] bg-no-repeat bg-[right_14px_center]"
							>
								<option value="member">Member</option>
								<option value="editor">Editor</option>
								<option value="admin">Admin</option>
							</select>
						</div>

						{/* Submit */}
						<button
							type="submit"
							disabled={isLoading}
							className="w-full py-3.5 rounded-full bg-[#111111] dark:bg-white text-white dark:text-[#111111] font-[family-name:var(--font-dm-sans)] text-[15px] font-semibold cursor-pointer shadow-[0_4px_12px_-2px_rgba(0,0,0,0.15)] transition-all hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
						>
							{isLoading ? "Creating invite..." : "Create invite"}
						</button>
					</form>
				)}
			</div>
		</div>
	);
}
