"use client";

import { useState } from "react";
import { RefreshCw, Unplug } from "lucide-react";
import ConfirmDialog from "@/components/ui/confirm-dialog";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { DropdownMenu } from "@/components/ui/dropdown-menu";
import { getApiErrorMessage } from "@/lib/api/errors";
import { cn } from "@/lib/utils";
import { useSkillsStore } from "@/stores/skills-store";
import {
	shortRevision,
	type SkillSource,
	type SkillSyncPlan,
	type SkillSyncStatus,
} from "@/types/skills";
import { relativeTime } from "../lib/relative-time";
import { SourceHostTile } from "./source-host-tile";
import { SourceStatusBadge } from "./source-status-badge";

interface SkillSourceTableProps {
	sources: SkillSource[];
	isLoading: boolean;
	canManage: boolean;
	onError: (message: string | null) => void;
}

const STATUS_COPY: Record<
	SkillSyncStatus,
	{ label: string; className: string; note?: string }
> = {
	new: {
		label: "NEW",
		className: "bg-success-bg text-success dark:bg-emerald-950 dark:text-emerald-300",
		note: "added to the library",
	},
	updated: {
		label: "UPDATED",
		className: "bg-warning-bg text-warning",
		note: "new version available to adopt",
	},
	unchanged: { label: "UNCHANGED", className: "bg-neutral-bg text-subtle dark:bg-white/10 dark:text-panel-body" },
	gone: {
		label: "GONE",
		className: "bg-[#FBEFED] text-[#B04A3A] dark:bg-[#B04A3A]/15",
		note: "keeps working, pinned",
	},
	skipped: {
		label: "SKIPPED",
		className: "bg-neutral-bg text-subtle dark:bg-white/10 dark:text-panel-body",
		note: "has an error",
	},
};

/**
 * What the sync is about to do, as the confirmation body.
 *
 * The point of showing it is that the four outcomes are not equally
 * consequential: only `new` changes the library on the spot. An `updated`
 * skill keeps running exactly as it does now until someone adopts the new
 * version, and a `gone` one keeps working too. Saying that here is what
 * makes the button safe to press.
 */
function SyncPlanSummary({ plan }: { plan: SkillSyncPlan }) {
	const order: SkillSyncStatus[] = ["new", "updated", "gone", "skipped", "unchanged"];
	const shown = [...plan.entries].sort(
		(a, b) => order.indexOf(a.status) - order.indexOf(b.status),
	);
	const changing = plan.entries.filter((e) => e.status !== "unchanged").length;
	return (
		<span className="block">
			<span className="block">
				{plan.currentRevision ? (
					<>
						<span className="font-mono text-[12.5px]">{shortRevision(plan.currentRevision)}</span> →{" "}
						<span className="font-mono text-[12.5px] font-semibold text-petrol">
							{shortRevision(plan.revision)}
						</span>
						. {changing === 0 ? "Nothing has changed." : `${changing} skill${changing === 1 ? "" : "s"} affected.`}
					</>
				) : (
					<>
						First sync, at{" "}
						<span className="font-mono text-[12.5px] font-semibold text-petrol">
							{shortRevision(plan.revision)}
						</span>
						.
					</>
				)}
			</span>
			{shown.length > 0 && (
				<span className="mt-3 block max-h-[280px] overflow-y-auto overflow-x-hidden rounded-[8px] border border-border [scrollbar-width:thin]">
					{shown.map((entry) => {
						const copy = STATUS_COPY[entry.status];
						return (
							<span
								key={`${entry.status}-${entry.name}-${entry.path}`}
								className="flex items-center gap-2 border-b border-hairline px-3 py-1.5 last:border-b-0 dark:border-white/5"
							>
								<span className="min-w-0 flex-1 truncate font-mono text-[12px] font-semibold text-petrol">
									{entry.name}
								</span>
								{copy.note && (
									<span className="shrink-0 text-[11px] text-meta dark:text-panel-dim">{copy.note}</span>
								)}
								<span
									className={cn(
										"shrink-0 rounded-[4px] px-1.5 py-px font-mono text-[9px] font-semibold tracking-[0.05em]",
										copy.className,
									)}
								>
									{copy.label}
								</span>
							</span>
						);
					})}
				</span>
			)}
			<span className="mt-2.5 block text-[12px] leading-[1.5] text-meta dark:text-panel-dim">
				Syncing does not change what an agent runs: an updated skill stays on its
				pinned version until you adopt it, one at a time, against a diff.
			</span>
		</span>
	);
}

/**
 * Row-scoped Sync button. Reads the repository, shows what the sync would
 * do, and only writes once that is confirmed — the read happens either way,
 * so there is no reason to write before showing it.
 */
function SyncButton({ source, onError }: { source: SkillSource; onError: (m: string | null) => void }) {
	const planSync = useSkillsStore((state) => state.planSync);
	const syncSource = useSkillsStore((state) => state.syncSource);
	const [busy, setBusy] = useState(false);
	const [plan, setPlan] = useState<SkillSyncPlan | null>(null);

	const open = () => {
		setBusy(true);
		onError(null);
		planSync(source.id)
			.then(setPlan)
			.catch((err: unknown) => {
				onError(getApiErrorMessage(err, "Could not read the repository."));
			})
			.finally(() => {
				setBusy(false);
			});
	};

	return (
		<>
			{plan && (
				<ConfirmDialog
					open
					onOpenChange={(next) => {
						if (!next) setPlan(null);
					}}
					title="Sync this repository?"
					description={<SyncPlanSummary plan={plan} />}
					confirmLabel="Sync"
					onConfirm={async () => {
						try {
							await syncSource(source.id);
						} catch (err) {
							onError(getApiErrorMessage(err, "Sync failed."));
						}
					}}
				/>
			)}
			<button
				type="button"
				disabled={busy}
				title="Read the repository again and see what would change"
				onClick={open}
				className="flex cursor-pointer items-center gap-1.5 rounded-[7px] border border-border px-[11px] py-[5px] text-[12px] font-semibold text-petrol transition-colors hover:bg-sidebar disabled:cursor-default dark:hover:bg-white/5"
			>
				<RefreshCw className={busy ? "size-3 animate-spin" : "size-3"} />
				{busy ? "Reading…" : "Sync"}
			</button>
		</>
	);
}

/**
 * The repositories the workspace syncs skills from (design 13b rows):
 * host tile + `owner/repo` + URL, the ref, the last sync's outcome, how many
 * skills it contributes, when it last ran. Sync and Disconnect are admin-only.
 */
export default function SkillSourceTable({ sources, isLoading, canManage, onError }: SkillSourceTableProps) {
	const deleteSource = useSkillsStore((state) => state.deleteSource);
	const [toDisconnect, setToDisconnect] = useState<SkillSource | null>(null);

	const columns: DataTableColumn<SkillSource>[] = [
		{
			key: "source",
			header: "Repository",
			width: "minmax(0, 1.5fr)",
			cell: (source) => (
				<div className="flex min-w-0 items-center gap-3">
					<SourceHostTile url={source.url} kind={source.kind} />
					<div className="min-w-0">
						<div className="truncate text-[13.5px] font-semibold text-foreground">{source.name}</div>
						<div className="mt-px truncate font-mono text-[11px] text-subtle dark:text-muted-foreground">
							{source.url.replace(/^https:\/\//, "")}
							{source.subpath ? ` · ${source.subpath}/` : ""}
						</div>
					</div>
				</div>
			),
		},
		{
			key: "ref",
			header: "Ref",
			width: "150px",
			hideBelowMd: true,
			cell: (source) => (
				<span className="block truncate font-mono text-[11px] text-subtle dark:text-muted-foreground">
					{source.ref}
					{source.lastRevision ? (
						<span className="text-meta dark:text-panel-dim"> @ {shortRevision(source.lastRevision)}</span>
					) : null}
				</span>
			),
		},
		{
			key: "status",
			header: "Status",
			width: "150px",
			mobileWidth: "auto",
			cell: (source) => (
				<div className="flex min-w-0 flex-col items-start gap-1">
					<SourceStatusBadge status={source.lastStatus} title={source.lastError} />
					{source.lastReport.length > 0 && (
						<span
							className="font-mono text-[10px] text-warning"
							title={source.lastReport
								.map((entry) => `${entry.path}: ${entry.issues.map((i) => `${i.code} ${i.message}`).join("; ")}`)
								.join("\n")}
						>
							{source.lastReport.length} skipped
						</span>
					)}
				</div>
			),
		},
		{
			key: "skills",
			header: "Skills",
			width: "80px",
			hideBelowMd: true,
			cell: (source) => (
				<span className="font-mono text-[11px] text-subtle dark:text-muted-foreground">{source.skillCount}</span>
			),
		},
		{
			key: "synced",
			header: "Last sync",
			width: "110px",
			hideBelowMd: true,
			cell: (source) => (
				<span className="font-mono text-[11px] text-meta dark:text-panel-dim">
					{source.lastSyncedAt ? relativeTime(source.lastSyncedAt) : "—"}
				</span>
			),
		},
		{
			key: "actions",
			header: "",
			width: "150px",
			mobileWidth: "auto",
			cell: (source) =>
				canManage ? (
					<div
						className="flex items-center justify-end gap-1.5"
						onClick={(e) => {
							e.stopPropagation();
						}}
					>
						<SyncButton source={source} onError={onError} />
						<DropdownMenu
							items={[
								{
									label: "Disconnect",
									icon: <Unplug />,
									destructive: true,
									onClick: () => {
										setToDisconnect(source);
									},
								},
							]}
						/>
					</div>
				) : null,
		},
	];

	return (
		<>
			<ConfirmDialog
				open={toDisconnect !== null}
				onOpenChange={(open) => {
					if (!open) setToDisconnect(null);
				}}
				title="Disconnect this repository?"
				description={
					<>
						<span className="font-mono text-[12.5px] font-semibold text-petrol">{toDisconnect?.name}</span> stops
						syncing. Its {toDisconnect?.skillCount ?? 0} skill{toDisconnect?.skillCount === 1 ? "" : "s"} stay in the
						library as in-app skills — editable here, no longer pinned to the repository — so no agent loses one.
					</>
				}
				confirmLabel="Disconnect"
				destructive
				onConfirm={async () => {
					if (toDisconnect) await deleteSource(toDisconnect.id);
				}}
				errorMessage="Could not disconnect the repository. Please try again."
			/>
			<DataTable
				columns={columns}
				rows={sources}
				rowKey={(source) => source.id}
				isLoading={isLoading}
				scrollBody
				emptyMessage="No repository connected yet."
			/>
		</>
	);
}
