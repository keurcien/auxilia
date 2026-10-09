"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, Check, Trash2 } from "lucide-react";
import {
	Dialog,
	DialogButton,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";

export interface BulkConfirmItem {
	id: string;
	name: string;
	blockedReason?: string;
	note?: string;
}

export interface BulkFailure {
	id: string;
	name: string;
	message: string;
}

interface BulkConfirmDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	title: string;
	description: React.ReactNode;
	items: BulkConfirmItem[];
	confirmLabel: string;
	busyLabel?: string;
	onConfirm: (actionableItems: BulkConfirmItem[]) => Promise<BulkFailure[]>;
}

export function BulkConfirmDialog({
	open,
	onOpenChange,
	title,
	description,
	items,
	confirmLabel,
	busyLabel = "Working…",
	onConfirm,
}: BulkConfirmDialogProps) {
	const [isBusy, setIsBusy] = useState(false);
	const [failures, setFailures] = useState<BulkFailure[]>([]);
	const actionable = useMemo(
		() => items.filter((item) => !item.blockedReason),
		[items],
	);
	const blocked = items.filter((item) => item.blockedReason);

	const handleOpenChange = (nextOpen: boolean) => {
		if (!nextOpen) {
			setIsBusy(false);
			setFailures([]);
		}
		onOpenChange(nextOpen);
	};

	const handleConfirm = async () => {
		setIsBusy(true);
		setFailures([]);
		try {
			const nextFailures = await onConfirm(actionable);
			if (nextFailures.length === 0) {
				handleOpenChange(false);
			} else {
				setFailures(nextFailures);
			}
		} catch {
			setFailures(
				actionable.map((item) => ({
					id: item.id,
					name: item.name,
					message: "The action could not be completed.",
				})),
			);
		} finally {
			setIsBusy(false);
		}
	};

	return (
		<Dialog open={open} onOpenChange={isBusy ? undefined : handleOpenChange}>
			<DialogContent className="overflow-hidden p-0 sm:max-w-[520px]">
				<div className="border-b border-border bg-gradient-to-b from-[#F8FBF9] to-card px-6 pb-5 pt-6 dark:border-white/10 dark:from-white/[0.04] dark:to-card">
					<div className="mb-4 flex size-10 items-center justify-center rounded-[11px] bg-[#FBEFED] text-[#B04A3A] shadow-[inset_0_0_0_1px_rgba(176,74,58,0.08)] dark:bg-[#B04A3A]/15">
						<Trash2 className="size-[18px]" />
					</div>
					<DialogHeader>
						<DialogTitle>{title}</DialogTitle>
						<DialogDescription>{description}</DialogDescription>
					</DialogHeader>
				</div>

				<div className="space-y-3 px-6 py-4">
					<div className="max-h-48 overflow-y-auto rounded-[9px] border border-border dark:border-white/10">
						{items.map((item) => (
							<div
								key={item.id}
								className="flex items-start gap-2.5 border-b border-hairline px-3 py-2.5 last:border-b-0 dark:border-white/5"
							>
								{item.blockedReason ? (
									<AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" />
								) : (
									<Check className="mt-0.5 size-3.5 shrink-0 text-success" />
								)}
								<div className="min-w-0 flex-1">
									<p className="truncate text-[12.5px] font-semibold text-foreground">
										{item.name}
									</p>
									{(item.blockedReason || item.note) && (
										<p className="mt-0.5 text-[11px] leading-[1.4] text-meta dark:text-panel-dim">
											{item.blockedReason ?? item.note}
										</p>
									)}
								</div>
							</div>
						))}
					</div>

					{blocked.length > 0 && (
						<div className="rounded-[9px] bg-warning-bg px-3.5 py-2.5 text-[12px] leading-[1.45] text-warning">
							{blocked.length} selected item{blocked.length === 1 ? " is" : "s are"} protected
							and will be left untouched.
						</div>
					)}
					{failures.length > 0 && (
						<div className="rounded-[9px] bg-[#FBEFED] px-3.5 py-2.5 text-[12px] leading-[1.45] text-[#B04A3A] dark:bg-[#B04A3A]/10">
							<p className="font-semibold">
								{failures.length} item{failures.length === 1 ? "" : "s"} could not be processed.
							</p>
							<ul className="mt-1 space-y-1">
								{failures.map((failure) => (
									<li key={failure.id}>
										<span className="font-semibold">{failure.name}:</span>{" "}
										{failure.message}
									</li>
								))}
							</ul>
						</div>
					)}
				</div>

				<DialogFooter className="border-t border-border px-6 py-4 dark:border-white/10">
					<DialogButton
						variant="outline"
						disabled={isBusy}
						onClick={() => {
							handleOpenChange(false);
						}}
					>
						{failures.length > 0 ? "Close" : "Cancel"}
					</DialogButton>
					{failures.length === 0 && actionable.length > 0 && (
						<DialogButton
							variant="destructive"
							disabled={isBusy}
							onClick={() => {
								void handleConfirm();
							}}
						>
							{isBusy ? busyLabel : `${confirmLabel} ${actionable.length}`}
						</DialogButton>
					)}
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}
