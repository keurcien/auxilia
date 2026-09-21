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
	type SkillSourceReportEntry,
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

const STATUS_COPY = new Map<
	SkillSyncStatus,
	{ label: string; className: string; note?: string }
>(Object.entries({
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
		// Overridden by the entry's own issue, which is the actual reason —
		// an invalid SKILL.md and a name already taken in the library are not
		// the same problem and do not have the same fix.
		note: "not imported",
	},
}) as [SkillSyncStatus, { label: string; className: string; note?: string }][]);

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
						const copy = STATUS_COPY.get(entry.status);
						if (!copy) return null;
						return (
							<span
								key={`${entry.status}-${entry.name}-${entry.path}`}
								className="flex items-center gap-2 border-b border-hairline px-3 py-1.5 last:border-b-0 dark:border-white/5"
							>
								<span className="min-w-0 shrink-0 max-w-[40%] truncate font-mono text-[12px] font-semibold text-petrol">
									{entry.name}
								</span>
								<span
									className="min-w-0 flex-1 truncate text-right text-[11px] text-meta dark:text-panel-dim"
									title={entry.issues.map((i) => `${i.code} ${i.message}`).join("\n")}
								>
									{entry.issues[0]?.message ?? copy.note ?? ""}
								</span>
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
 * What the last sync did, under the status badge — the counterpart to the
 * plan the Sync button shows beforehand.
 *
 * A sync is the one thing here that changes the library while nobody is
 * looking at the dialog that described it, so the row has to be able to
 * answer "what happened?" afterwards. A quiet `unchanged` is left out of the
 * count — it is the majority of a steady-state sync and "14 unchanged" buries
 * the line that matters — but one carrying a warning is not quiet, and is
 * counted and listed. The title names every entry by skill *and* path.
 */
function LastSyncOutcome({ report }: { report: SkillSourceReportEntry[] }) {
	const counted: SkillSyncStatus[] = ["new", "updated", "gone", "skipped"];
	const parts = counted
		.map((status) => ({ status, n: report.filter((e) => e.status === status).length }))
		.filter((part) => part.n > 0);
	// An `unchanged` skill can still carry a warning — a validation issue that
	// does not stop the import. Those are the entries a steady-state sync is
	// made of, so dropping them silently is how a warning goes unseen forever.
	const noted = report.filter((e) => e.status !== "unchanged" || e.issues.length > 0);
	if (parts.length === 0 && noted.length === 0) return null;
	const tone = noted.some(
		(e) => e.status === "skipped" || e.status === "gone" || e.issues.length > 0,
	)
		? "text-warning"
		: "text-meta dark:text-panel-dim";
	const warnings = noted.filter((e) => e.status === "unchanged").length;
	const summary = [
		...parts.map((p) => `${p.n} ${STATUS_COPY.get(p.status)?.label.toLowerCase()}`),
		...(warnings > 0 ? [`${warnings} warned`] : []),
	].join(" · ");
	return (
		<span
			className={cn("truncate font-mono text-[10px]", tone)}
			// The path, not just the name: two skills in one repository can
			// share a name (that is the `W003` skip), and the name alone cannot
			// say which folder to go and fix.
			title={noted
				.map((e) =>
					[
						`${e.name} (${e.path}): ${e.status}`,
						...e.issues.map((i) => `  ${i.code} ${i.message}`),
					].join("\n"),
				)
				.join("\n")}
		>
			{summary}
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
					<LastSyncOutcome report={source.lastReport} />
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
						library — files and scripts included, still running, frozen at the commit they are pinned to. Their
						content is edited nowhere until you connect <span className="font-semibold">this same URL</span> again,
						which re-pins the very same skills, keeping the agents that use them. Their names stay taken meanwhile,
						so another repository cannot quietly take one over.
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
