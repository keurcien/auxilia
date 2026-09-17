"use client";

import { useState } from "react";
import { RefreshCw, Unplug } from "lucide-react";
import ConfirmDialog from "@/components/ui/confirm-dialog";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { DropdownMenu } from "@/components/ui/dropdown-menu";
import { getApiErrorMessage } from "@/lib/api/errors";
import { useSkillsStore } from "@/stores/skills-store";
import { shortRevision, type SkillSource } from "@/types/skills";
import { relativeTime } from "../lib/relative-time";
import { SourceHostTile } from "./source-host-tile";
import { SourceStatusBadge } from "./source-status-badge";

interface SkillSourceTableProps {
	sources: SkillSource[];
	isLoading: boolean;
	canManage: boolean;
	onError: (message: string | null) => void;
}

/** Row-scoped Sync button: spins while the host is read. */
function SyncButton({ source, onError }: { source: SkillSource; onError: (m: string | null) => void }) {
	const syncSource = useSkillsStore((state) => state.syncSource);
	const [busy, setBusy] = useState(false);
	return (
		<button
			type="button"
			disabled={busy}
			title="Read the repository again and make new versions available"
			onClick={() => {
				setBusy(true);
				onError(null);
				syncSource(source.id)
					.catch((err: unknown) => {
						onError(getApiErrorMessage(err, "Sync failed."));
					})
					.finally(() => {
						setBusy(false);
					});
			}}
			className="flex cursor-pointer items-center gap-1.5 rounded-[7px] border border-border px-[11px] py-[5px] text-[12px] font-semibold text-petrol transition-colors hover:bg-sidebar disabled:cursor-default dark:hover:bg-white/5"
		>
			<RefreshCw className={busy ? "size-3 animate-spin" : "size-3"} />
			{busy ? "Syncing…" : "Sync"}
		</button>
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
