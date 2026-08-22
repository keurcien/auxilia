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
import type { BoundAgent } from "@/types/agents";

interface ResourceInUseDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	/** e.g. "Sandbox" / "MCP server" — used in the title and body copy. */
	resourceLabel: string;
	resourceName: string | null;
	/** Agents still bound to the resource — the reason plain delete is refused. */
	agents: BoundAgent[];
	/** What the listed agents lose, e.g. "they lose code execution". */
	consequence: string;
	/** Detach the resource from all listed agents, then delete it. */
	onConfirm: () => Promise<void>;
}

export default function ResourceInUseDialog({
	open,
	onOpenChange,
	resourceLabel,
	resourceName,
	agents,
	consequence,
	onConfirm,
}: ResourceInUseDialogProps) {
	const [isDeleting, setIsDeleting] = useState(false);
	const [error, setError] = useState<string | null>(null);

	const handleConfirm = async () => {
		setIsDeleting(true);
		setError(null);
		try {
			await onConfirm();
			onOpenChange(false);
		} catch {
			setError(`Could not delete the ${resourceLabel.toLowerCase()}. Please try again.`);
		} finally {
			setIsDeleting(false);
		}
	};

	if (!resourceName) return null;

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="sm:max-w-[480px]">
				<DialogHeader>
					<DialogTitle>{resourceLabel} in use</DialogTitle>
					<DialogDescription>
						&ldquo;{resourceName}&rdquo; can&apos;t be removed — it&apos;s
						still enabled on {agents.length === 1 ? "this agent" : "these agents"}:
					</DialogDescription>
				</DialogHeader>

				{error && (
					<div className="rounded-[10px] bg-[#FBEFED] px-3.5 py-2.5 text-[13px] font-medium text-[#B04A3A] dark:bg-[#B04A3A]/10">
						{error}
					</div>
				)}

				<div className="max-h-[240px] overflow-y-auto rounded-[10px] border border-hairline dark:border-white/10 [scrollbar-width:thin]">
					{agents.map((agent) => (
						<div
							key={agent.id}
							className="flex items-center gap-2.5 border-b border-hairline px-3.5 py-2.5 last:border-b-0 dark:border-white/5"
						>
							<span
								className="flex size-[26px] shrink-0 items-center justify-center rounded-[6px] text-[13px]"
								style={{ backgroundColor: `${agent.color ?? "#9E9E9E"}1A` }}
							>
								{agent.emoji ?? "🤖"}
							</span>
							<span className="truncate text-[13.5px] font-semibold text-foreground">
								{agent.name}
							</span>
						</div>
					))}
				</div>

				<p className="text-[13px] leading-[1.55] text-subtle dark:text-panel-body">
					Removing it will detach the {resourceLabel.toLowerCase()} from{" "}
					{agents.length === 1 ? "this agent" : `these ${agents.length} agents`}{" "}
					— {consequence}. Threads are unaffected.
				</p>

				<DialogFooter>
					<DialogButton
						variant="outline"
						onClick={() => {
							onOpenChange(false);
						}}
					>
						Cancel
					</DialogButton>
					<button
						type="button"
						disabled={isDeleting}
						onClick={() => {
							void handleConfirm();
						}}
						className="inline-flex cursor-pointer items-center justify-center rounded-[7px] bg-[#B04A3A] px-4 py-2 text-[12.5px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-default disabled:opacity-50"
					>
						{isDeleting
							? "Removing…"
							: `Detach from ${agents.length === 1 ? "1 agent" : `${agents.length} agents`} & delete`}
					</button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}
