"use client";

import {
	Check,
	Copy,
	Globe2,
	LoaderCircle,
	LockKeyhole,
	LockKeyholeOpen,
	Share2,
} from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { ChatHeaderActions, HeaderTip } from "@/components/layout/chat-header";
import ConfirmDialog from "@/components/ui/confirm-dialog";
import {
	Dialog,
	DialogButton,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
	createConversationShare,
	deleteConversationShare,
	getConversationShare,
	type ConversationShare,
} from "@/lib/api/resources/threads";

function publicUrl(share: ConversationShare): string {
	return `${window.location.origin}/share/${share.id}#token=${encodeURIComponent(share.token)}`;
}

export function ShareConversation({
	threadId,
	disabled,
	variant = "header",
}: {
	threadId: string;
	disabled: boolean;
	variant?: "header" | "menu";
}) {
	const [open, setOpen] = useState(false);
	const [share, setShare] = useState<ConversationShare | null | undefined>();
	const [busy, setBusy] = useState(false);
	const [copied, setCopied] = useState(false);
	const [confirmRevoke, setConfirmRevoke] = useState(false);

	useEffect(() => {
		setShare(undefined);
		setCopied(false);
	}, [threadId]);

	useEffect(() => {
		if ((!open && variant !== "menu") || share !== undefined) return;
		let active = true;
		void getConversationShare(threadId).then(
			(value) => {
				if (active) setShare(value);
			},
			(error: unknown) => {
				if (active) {
					setShare(null);
					toast.error(
						getApiErrorMessage(error, "Could not load sharing status"),
					);
				}
			},
		);
		return () => {
			active = false;
		};
	}, [open, share, threadId, variant]);

	const publish = async () => {
		setBusy(true);
		try {
			const value = await createConversationShare(threadId);
			setShare(value);
			toast.success("Conversation published");
		} catch (error) {
			toast.error(getApiErrorMessage(error, "Could not publish conversation"));
		} finally {
			setBusy(false);
		}
	};

	const copy = async () => {
		if (!share) return;
		try {
			await navigator.clipboard.writeText(publicUrl(share));
			setCopied(true);
			toast.success("Public link copied");
		} catch {
			toast.error("Could not copy the public link");
		}
	};

	const revoke = async () => {
		await deleteConversationShare(threadId);
		setShare(null);
		setConfirmRevoke(false);
		toast.success("Publication removed");
	};

	const trigger =
		variant === "menu" ? (
			<button
				type="button"
				disabled={disabled}
				onClick={() => {
					setOpen(true);
				}}
				className={`group relative min-h-32 w-full touch-manipulation cursor-pointer overflow-hidden rounded-[13px] border px-5 py-5 text-left transition-[background-color,border-color,transform] active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-45 ${
					share
						? "border-emerald-500/25 bg-emerald-500/[0.07] hover:bg-emerald-500/[0.11]"
						: share === null
							? "border-sidebar-border bg-card hover:bg-sidebar-hover"
							: "border-sidebar-border bg-sidebar-accent/45 hover:border-border-hover hover:bg-sidebar-accent/70"
				}`}
			>
				<span className="flex items-start justify-between gap-4">
					<span>
						<span className="flex items-center gap-2.5 text-[15px] font-semibold text-sidebar-foreground">
							<Share2 className="size-[18px] text-sidebar-active-icon" />
							Share conversation
						</span>
						<span className="mt-3 block max-w-[255px] text-[13.5px] leading-5 text-sidebar-muted">
							{share
								? "A read-only snapshot is active. Open it to copy or revoke the link."
								: "Publish a read-only snapshot and send its private link."}
						</span>
					</span>
					<span
						title={
							share === undefined
								? "Checking sharing status"
								: share
									? "Sharing active"
									: "Conversation private"
						}
						className={`flex size-9 shrink-0 items-center justify-center rounded-full border ${
							share === undefined
								? "border-sidebar-border bg-card text-sidebar-muted"
								: share
									? "border-emerald-500/25 bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
									: "border-sidebar-border bg-sidebar-accent text-sidebar-active-icon"
						}`}
					>
						{share === undefined ? (
							<LoaderCircle className="size-4 animate-spin" />
						) : share ? (
							<LockKeyholeOpen className="size-4" />
						) : (
							<LockKeyhole className="size-4" />
						)}
					</span>
				</span>
			</button>
		) : (
			<HeaderTip
				label="Share"
				hint={
					disabled
						? "Available once the conversation has messages and the agent is idle"
						: "Publish a read-only snapshot with a private link"
				}
			>
				<span className="inline-flex">
					<button
						type="button"
						aria-label="Share conversation"
						disabled={disabled}
						onClick={() => {
							setOpen(true);
						}}
						className="flex size-[30px] cursor-pointer items-center justify-center rounded-full bg-petrol-chip text-petrol transition-colors hover:bg-petrol-tint disabled:cursor-not-allowed disabled:opacity-50 dark:bg-white/10 dark:text-panel-terminal dark:hover:bg-white/15"
					>
						<Share2 className="size-3.5" />
					</button>
				</span>
			</HeaderTip>
		);

	return (
		<>
			{variant === "header" ? (
				<ChatHeaderActions>{trigger}</ChatHeaderActions>
			) : (
				trigger
			)}

			<Dialog open={open} onOpenChange={setOpen}>
				<DialogContent>
					<DialogHeader>
						<DialogTitle>Share conversation</DialogTitle>
						<DialogDescription>
							Publish a read-only snapshot. New messages added later will not
							appear in the shared version.
						</DialogDescription>
					</DialogHeader>

					{share === undefined ? (
						<div className="h-20 animate-pulse rounded-[10px] bg-hover dark:bg-white/5" />
					) : share === null ? (
						<div className="rounded-[10px] border border-input p-4">
							<div className="flex items-start gap-3">
								<span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-petrol-tint text-petrol">
									<Globe2 className="size-4" />
								</span>
								<div>
									<p className="text-[13px] font-semibold text-foreground">
										Anyone with the link can view this snapshot
									</p>
									<p className="mt-1 text-[12px] leading-5 text-subtle">
										They cannot send messages, approve tools, or interact with
										the agent.
									</p>
								</div>
							</div>
						</div>
					) : (
						<div className="space-y-3">
							<div className="flex items-center gap-2 rounded-[9px] border border-input bg-hover/40 p-2 dark:border-white/10 dark:bg-white/[0.04]">
								<input
									readOnly
									value={publicUrl(share)}
									aria-label="Public conversation link"
									className="min-w-0 flex-1 bg-transparent px-1 font-mono text-[11.5px] text-foreground outline-none dark:text-panel-button"
								/>
								<button
									type="button"
									onClick={() => {
										void copy();
									}}
									className="flex h-8 shrink-0 cursor-pointer items-center gap-1.5 rounded-[7px] bg-petrol px-3 text-[12px] font-semibold text-white"
								>
									{copied ? (
										<Check className="size-3.5" />
									) : (
										<Copy className="size-3.5" />
									)}
									{copied ? "Copied" : "Copy"}
								</button>
							</div>
							<p className="text-[12px] leading-5 text-subtle">
								The link stays active until you stop sharing it.
							</p>
						</div>
					)}

					<DialogFooter>
						{share ? (
							<>
								<DialogButton
									variant="outline"
									onClick={() => {
										setConfirmRevoke(true);
									}}
								>
									Stop sharing
								</DialogButton>
								<DialogButton
									variant="primary"
									onClick={() => {
										void copy();
									}}
								>
									Copy link
								</DialogButton>
							</>
						) : (
							<DialogButton
								variant="primary"
								disabled={busy || share === undefined}
								onClick={() => {
									void publish();
								}}
							>
								{busy ? "Publishing…" : "Publish snapshot"}
							</DialogButton>
						)}
					</DialogFooter>
				</DialogContent>
			</Dialog>

			<ConfirmDialog
				open={confirmRevoke}
				onOpenChange={setConfirmRevoke}
				title="Stop sharing this conversation?"
				description="The public link will stop working immediately."
				confirmLabel="Stop sharing"
				destructive
				onConfirm={revoke}
			/>
		</>
	);
}
