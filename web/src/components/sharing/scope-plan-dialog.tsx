"use client";

import { useCallback, useRef, useState } from "react";
import {
	AlarmClock,
	AlertTriangle,
	ArrowRight,
	Bot,
	Folder,
	Info,
	ScrollText,
	Server,
	Share2,
	type LucideIcon,
} from "lucide-react";
import {
	Dialog,
	DialogButton,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { VisibilityBadge } from "@/components/ui/visibility-badge";
import { getApiErrorMessage } from "@/lib/api/errors";
import * as sharingApi from "@/lib/api/resources/sharing";
import { cn } from "@/lib/utils";
import type {
	ScopeChange,
	ScopeChangeRole,
	ScopePlan,
	ScopePlanItem,
	ScopeResourceKind,
} from "@/types/sharing";

/**
 * `proceed`: only the requested resource changes, the caller saves it as
 * usual. `applied`: the plan, requested change included, is already saved.
 */
export type ScopeChangeOutcome = "proceed" | "applied" | "cancelled";

const KIND_META: Record<ScopeResourceKind, { label: string; Icon: LucideIcon }> = {
	agent: { label: "Agent", Icon: Bot },
	project: { label: "Project", Icon: Folder },
	trigger: { label: "Trigger", Icon: AlarmClock },
	mcp_server: { label: "MCP server", Icon: Server },
	skill: { label: "Skill", Icon: ScrollText },
};

const ROLE_META: Record<ScopeChangeRole, { label: string; className: string }> = {
	target: {
		label: "Requested",
		className: "bg-petrol-tint text-petrol dark:bg-white/10 dark:text-panel-terminal",
	},
	required: {
		label: "Required",
		className: "bg-warning-bg text-warning",
	},
	suggested: {
		label: "Suggested",
		className: "bg-hover text-subtle dark:bg-white/10 dark:text-panel-body",
	},
};

function plural(count: number, word: string): string {
	return `${count} ${word}${count === 1 ? "" : "s"}`;
}

function PlanRow({ item }: { item: ScopePlanItem }) {
	const { label, Icon } = KIND_META[item.kind];
	const role = ROLE_META[item.role];
	return (
		<div
			className="flex items-start gap-2.5 border-b border-hairline py-2.5 pr-3 last:border-b-0 dark:border-white/5"
			style={{ paddingLeft: 12 + item.depth * 20 }}
		>
			<Icon className="mt-0.5 size-3.5 shrink-0 text-meta" />
			<div className="min-w-0 flex-1 space-y-1.5">
				<div className="flex min-w-0 items-center gap-2">
					<span className="truncate text-[12.5px] font-semibold text-foreground">
						{item.name}
					</span>
					<span className="shrink-0 text-[11px] text-meta">{label}</span>
					<span
						className={cn(
							"ml-auto shrink-0 rounded-full px-2 py-0.5 text-[10.5px] font-semibold",
							role.className,
						)}
					>
						{role.label}
					</span>
				</div>
				<div className="flex flex-wrap items-center gap-1.5">
					<VisibilityBadge
						visibility={item.currentVisibility}
						teamIds={item.currentTeamIds}
						showTeams
					/>
					<ArrowRight className="size-3 shrink-0 text-meta" />
					<VisibilityBadge
						visibility={item.visibility}
						teamIds={item.teamIds}
						showTeams
					/>
				</div>
				{item.reason && (
					<p className="text-[11px] leading-[1.4] text-meta dark:text-panel-dim">
						{item.reason}
					</p>
				)}
				{!item.canManage && (
					<p className="flex items-center gap-1 text-[11px] leading-[1.4] text-warning">
						<AlertTriangle className="size-3 shrink-0" />
						You cannot change this one yourself.
					</p>
				)}
			</div>
		</div>
	);
}

interface ScopePlanDialogProps {
	plan: ScopePlan;
	onResolve: (outcome: ScopeChangeOutcome) => void;
}

function ScopePlanDialog({ plan, onResolve }: ScopePlanDialogProps) {
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const target = plan.items.find((item) => item.role === "target");
	const blocked = plan.blockers.length > 0;
	const allChanges = plan.complete ?? plan.minimal;
	const requiredCount = plan.items.filter((item) => item.role === "required").length;
	const suggestedCount = plan.items.filter((item) => item.role === "suggested").length;
	const targetOnlyAllowed = !blocked && plan.complete !== null && plan.minimal.length === 1;
	const requiredOnlyAllowed = !blocked && plan.complete !== null && plan.minimal.length > 1;

	const apply = async (changes: ScopeChange[]) => {
		setBusy(true);
		setError(null);
		try {
			await sharingApi.applyScopeChanges(changes);
			onResolve("applied");
		} catch (err) {
			setError(getApiErrorMessage(err, "The access changes could not be applied."));
			setBusy(false);
		}
	};

	const summary = [
		requiredCount > 0 && plural(requiredCount, "required change"),
		suggestedCount > 0 && plural(suggestedCount, "suggestion"),
	]
		.filter(Boolean)
		.join(" and ");

	return (
		<Dialog
			open
			onOpenChange={(open) => {
				if (!open && !busy) onResolve("cancelled");
			}}
		>
			<DialogContent className="overflow-hidden p-0 sm:max-w-[600px]">
				<div className="border-b border-border bg-gradient-to-b from-[#F4F9F9] to-card px-6 pb-5 pt-6 dark:border-white/10 dark:from-white/[0.04] dark:to-card">
					<div className="mb-4 flex size-10 items-center justify-center rounded-[11px] bg-petrol-tint text-petrol dark:bg-white/10 dark:text-panel-terminal">
						<Share2 className="size-[18px]" />
					</div>
					<DialogHeader>
						<DialogTitle>Review access changes</DialogTitle>
						<DialogDescription>
							{target ? (
								<>
									Changing who can access <strong>{target.name}</strong>{" "}
									affects the resources it is linked to
									{summary ? `: ${summary}.` : "."}
								</>
							) : (
								"This change affects linked resources."
							)}
						</DialogDescription>
					</DialogHeader>
				</div>

				<div className="space-y-3 px-6 py-4">
					{plan.note && (
						<div className="flex items-start gap-2 rounded-[9px] bg-petrol-tint px-3.5 py-2.5 text-[12px] leading-[1.45] text-petrol dark:bg-white/5 dark:text-panel-dim">
							<Info className="mt-0.5 size-3.5 shrink-0" />
							{plan.note}
						</div>
					)}
					<div className="max-h-[46vh] overflow-y-auto rounded-[9px] border border-border dark:border-white/10">
						{plan.items.map((item) => (
							<PlanRow key={`${item.kind}:${item.id}`} item={item} />
						))}
					</div>
					{blocked && (
						<div className="rounded-[9px] bg-[#FBEFED] px-3.5 py-2.5 text-[12px] leading-[1.45] text-[#B04A3A] dark:bg-[#B04A3A]/10">
							<p className="font-semibold">This change cannot be applied yet.</p>
							<ul className="mt-1 list-disc space-y-1 pl-4">
								{plan.blockers.map((blocker) => (
									<li key={blocker}>{blocker}</li>
								))}
							</ul>
						</div>
					)}
					{targetOnlyAllowed && (
						<p className="text-[11.5px] leading-[1.45] text-meta dark:text-panel-dim">
							The suggestions are optional: you can change only{" "}
							{target?.name ?? "the requested resource"} and share the rest later.
						</p>
					)}
					{error && (
						<div className="rounded-[9px] bg-[#FBEFED] px-3.5 py-2.5 text-[12px] leading-[1.45] text-[#B04A3A] dark:bg-[#B04A3A]/10">
							{error}
						</div>
					)}
				</div>

				<DialogFooter className="border-t border-border px-6 py-4 dark:border-white/10">
					<DialogButton
						variant="outline"
						disabled={busy}
						onClick={() => {
							onResolve("cancelled");
						}}
					>
						Cancel
					</DialogButton>
					{targetOnlyAllowed && target && (
						<DialogButton
							variant="outline"
							disabled={busy}
							onClick={() => {
								onResolve("proceed");
							}}
						>
							Only this {KIND_META[target.kind].label.toLowerCase()}
						</DialogButton>
					)}
					{requiredOnlyAllowed && (
						<DialogButton
							variant="outline"
							disabled={busy}
							onClick={() => {
								void apply(plan.minimal);
							}}
						>
							Skip suggestions
						</DialogButton>
					)}
					{!blocked && (
						<DialogButton
							disabled={busy}
							onClick={() => {
								void apply(allChanges);
							}}
						>
							{busy ? "Applying…" : `Apply ${plural(allChanges.length, "change")}`}
						</DialogButton>
					)}
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}

/**
 * Asks the backend what a visibility change implies and, when it touches
 * anything beyond the requested resource, lets the user review the whole
 * plan in a dialog before anything is saved. Render `dialog` once.
 */
export function useScopeChangePlanner() {
	const [plan, setPlan] = useState<ScopePlan | null>(null);
	const resolveRef = useRef<((outcome: ScopeChangeOutcome) => void) | null>(null);

	const requestScopeChange = useCallback(
		async (change: ScopeChange): Promise<ScopeChangeOutcome> => {
			const next = await sharingApi.planScopeChange(change);
			const onlyTarget =
				next.blockers.length === 0 &&
				next.complete === null &&
				next.note === null &&
				next.minimal.length <= 1;
			if (onlyTarget) return "proceed";
			resolveRef.current?.("cancelled");
			return new Promise<ScopeChangeOutcome>((resolve) => {
				resolveRef.current = resolve;
				setPlan(next);
			});
		},
		[],
	);

	const resolve = useCallback((outcome: ScopeChangeOutcome) => {
		resolveRef.current?.(outcome);
		resolveRef.current = null;
		setPlan(null);
	}, []);

	const dialog = plan ? <ScopePlanDialog plan={plan} onResolve={resolve} /> : null;
	return { requestScopeChange, dialog };
}
