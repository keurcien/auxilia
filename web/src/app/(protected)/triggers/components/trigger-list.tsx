"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
	AlarmClock,
	Clock,
	Copy,
	Pause,
	Pencil,
	Play,
	Plus,
	Trash2,
	TriangleAlert,
	Webhook,
} from "lucide-react";
import { toast } from "sonner";
import TriggerCard from "@/app/(protected)/triggers/components/trigger-card";
import {
	BulkConfirmDialog,
	type BulkFailure,
} from "@/components/ui/bulk-confirm-dialog";
import { BulkActionBar } from "@/components/ui/bulk-action-bar";
import { Checkbox } from "@/components/ui/checkbox";
import { useConfirmDialog } from "@/components/providers/dialog-provider";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { DropdownMenu } from "@/components/ui/dropdown-menu";
import { GroupedCardTree } from "@/components/ui/grouped-card-tree";
import { SelectableLeading } from "@/components/ui/selectable-leading";
import type { ViewMode } from "@/components/ui/view-toggle";
import { useRunTrigger } from "@/hooks/use-run-trigger";
import {
	describeSchedule,
	formatRunAt,
	parseCronExpression,
} from "@/lib/triggers/schedule";
import { buildGroupTree, flattenGroupTree } from "@/lib/groups";
import { useRowSelection } from "@/hooks/use-row-selection";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
	matchesResourceScope,
	type ResourceScopeFilter,
} from "@/lib/resource-scope-filter";
import { useTriggersStore } from "@/stores/triggers-store";
import { useAgentsStore } from "@/stores/agents-store";
import type { Trigger } from "@/types/triggers";

interface TriggerListProps {
	view: "active" | "paused";
	mode: ViewMode;
	onCreate: () => void;
	canCreate: boolean;
	search: string;
	scope: ResourceScopeFilter;
	filterTeamIds: string[];
	onClearSearch: () => void;
}

function triggerFrequency(trigger: Trigger): string {
	return trigger.triggerType === "schedule"
		? describeSchedule(parseCronExpression(trigger.cronExpression))
		: "Webhook";
}

export default function TriggerList({
	view,
	mode,
	onCreate,
	canCreate,
	search,
	scope,
	filterTeamIds,
	onClearSearch,
}: TriggerListProps) {
	const router = useRouter();
	const triggers = useTriggersStore((state) => state.triggers);
	const isInitialized = useTriggersStore((state) => state.isInitialized);
	const fetchTriggers = useTriggersStore((state) => state.fetchTriggers);
	const updateTrigger = useTriggersStore((state) => state.updateTrigger);
	const createTrigger = useTriggersStore((state) => state.createTrigger);
	const deleteTrigger = useTriggersStore((state) => state.deleteTrigger);
	const agents = useAgentsStore((state) => state.agents);
	const fetchAgents = useAgentsStore((state) => state.fetchAgents);
	const confirmDialog = useConfirmDialog();
	const runTrigger = useRunTrigger();
	const [bulkOpen, setBulkOpen] = useState(false);

	useEffect(() => {
		fetchTriggers().catch(() => {});
		fetchAgents().catch(() => {});
	}, [fetchTriggers, fetchAgents]);

	const query = search.trim().toLowerCase();
	const visibleTriggers = triggers.filter((trigger) => {
		if (view === "active" ? !trigger.isActive : trigger.isActive) return false;
		if (!matchesResourceScope(trigger, scope, filterTeamIds)) return false;
		if (!query) return true;
		const agentName = agents.find(
			(candidate) => candidate.id === trigger.agentId,
		)?.name;
		return [
			trigger.name,
			trigger.instructions,
			trigger.group,
			trigger.timezone,
			triggerFrequency(trigger),
			agentName,
		].some((value) => value?.toLowerCase().includes(query));
	});
	const groupTree = useMemo(
		() => buildGroupTree(visibleTriggers),
		[visibleTriggers],
	);
	const orderedTriggers = useMemo(() => flattenGroupTree(groupTree), [groupTree]);
	const manageableTriggerIds = orderedTriggers
		.filter((trigger) => trigger.canManage)
		.map((trigger) => trigger.id);
	const selection = useRowSelection({
		orderedIds: orderedTriggers.map((trigger) => trigger.id),
		eligibleIds: manageableTriggerIds,
	});
	const selectedTriggers = orderedTriggers.filter((trigger) =>
		selection.selectedIds.has(trigger.id),
	);

	const handleDelete = async (id: string) => {
		if (
			!(await confirmDialog({
				title: "Delete this trigger?",
				description:
					"Its configuration will be removed permanently. Existing run history is unaffected.",
				confirmLabel: "Delete trigger",
				destructive: true,
			}))
		) {
			return;
		}
		deleteTrigger(id).catch((error) => {
			console.error("Error deleting trigger:", error);
			toast.error("Failed to delete trigger. Please try again.");
		});
	};

	const handleDuplicate = async (trigger: Trigger) => {
		if (!canCreate) return;
		try {
			const base = {
				name: `${trigger.name} copy`,
				group: trigger.group,
				instructions: trigger.instructions,
				agentId: trigger.agentId,
				modelId: trigger.modelId,
				reasoningEffort: trigger.reasoningEffort,
				isActive: false,
				visibility: trigger.visibility,
				teamIds: trigger.teamIds,
			};
			const created =
				trigger.triggerType === "schedule"
					? await createTrigger({
							...base,
							triggerType: "schedule",
							cronExpression: trigger.cronExpression,
							timezone: trigger.timezone,
						})
					: await createTrigger({
							...base,
							triggerType: "webhook",
						});
			toast.success(`Duplicated as “${created.name}” and paused.`);
			router.push(`/triggers/${created.id}`);
		} catch (error: unknown) {
			toast.error(
				getApiErrorMessage(error, "Could not duplicate the trigger."),
			);
		}
	};

	const handleRunNow = (trigger: Trigger) => {
		runTrigger(trigger).catch((error: unknown) => {
			console.error("Error running trigger:", error);
			toast.error("Failed to run the trigger. Please try again.");
		});
	};

	const handleToggleActive = (trigger: Trigger) => {
		updateTrigger(trigger.id, { isActive: !trigger.isActive }).catch(
			(error: unknown) => {
				console.error("Error updating trigger:", error);
				toast.error("Failed to update trigger. Please try again.");
			},
		);
	};

	const columns: DataTableColumn<Trigger>[] = [
		{
			key: "name",
			header: selection.selectionMode ? (
				""
			) : (
				<span className="flex items-center gap-2.5">
					<Checkbox
						checked={false}
						aria-label="Select all triggers"
						onCheckedChange={selection.toggleAll}
					/>
					<button
						type="button"
						onClick={selection.toggleAll}
						className="cursor-pointer text-[12px]! font-semibold text-foreground hover:text-petrol"
					>
						Select all
					</button>
				</span>
			),
			width: "minmax(240px, 1.5fr)",
			cell: (trigger) => (
				<div className="flex min-w-0 items-center gap-2.5">
					<SelectableLeading
						selected={selection.isSelected(trigger.id)}
						selectionMode={selection.selectionMode}
						disabled={!trigger.canManage}
						label={`Select ${trigger.name}`}
						onToggle={(shiftKey) => {
							selection.toggle(trigger.id, shiftKey);
						}}
						className="size-[18px]"
					>
						<span
							className={`block size-2 rounded-full ${
								trigger.isActive ? "bg-success" : "bg-faint"
							}`}
						/>
					</SelectableLeading>
					<div className="min-w-0">
						<div className="flex min-w-0 items-center gap-2">
							<span className="truncate text-[12.5px] font-semibold text-foreground">
								{trigger.name}
							</span>
							{!trigger.modelAvailable && (
								<TriangleAlert
									className="size-3.5 shrink-0 text-warning"
									aria-label="Model unavailable"
								/>
							)}
						</div>
						<p className="mt-px truncate text-[11.5px] text-meta dark:text-panel-dim">
							{trigger.instructions}
						</p>
					</div>
				</div>
			),
		},
		{
			key: "agent",
			header: "Agent",
			width: "200px",
			cell: (trigger) => {
				const agent = agents.find((candidate) => candidate.id === trigger.agentId);
				return (
					<div className="flex min-w-0 items-center gap-2">
						<AgentAvatar
							agentId={agent?.id}
							name={agent?.name}
							imageRevision={agent?.imageRevision}
							color={agent?.color}
							emoji={agent?.emoji}
							size="xs"
						/>
						<span className="truncate text-[12px] font-medium text-subtle dark:text-muted-foreground">
							{agent?.name ?? "Unknown agent"}
						</span>
					</div>
				);
			},
		},
		{
			key: "frequency",
			header: "Frequency",
			width: "210px",
			cell: (trigger) => (
				<div className="flex min-w-0 items-center gap-2 text-[11.5px] text-subtle dark:text-muted-foreground">
					{trigger.triggerType === "schedule" ? (
						<Clock className="size-3.5 shrink-0 text-meta" />
					) : (
						<Webhook className="size-3.5 shrink-0 text-meta" />
					)}
					<span className="truncate">{triggerFrequency(trigger)}</span>
				</div>
			),
		},
		{
			key: "nextRun",
			header: "Next run",
			width: "180px",
			cell: (trigger) => (
				<span className="font-mono text-[11px] text-meta dark:text-panel-dim">
					{trigger.triggerType === "webhook"
						? trigger.isActive
							? "On request"
							: "Paused"
						: trigger.nextRunAt
							? formatRunAt(trigger.nextRunAt, trigger.timezone)
							: "Paused"}
				</span>
			),
		},
		{
			key: "actions",
			header: "",
			width: "44px",
			mobileWidth: "44px",
			cell: (trigger) =>
				trigger.canManage ? (
					<div
						className="flex justify-end"
						onClick={(event) => {
							event.stopPropagation();
						}}
					>
						<DropdownMenu
							items={[
								{
									label: "Run now",
									icon: <Play />,
									onClick: () => {
										handleRunNow(trigger);
									},
								},
								{
									label: trigger.isActive ? "Pause" : "Resume",
									icon: trigger.isActive ? <Pause /> : <Play />,
									onClick: () => {
										handleToggleActive(trigger);
									},
								},
								{
									label: "Edit",
									icon: <Pencil />,
									onClick: () => {
										router.push(`/triggers/${trigger.id}`);
									},
								},
								...(canCreate
									? [
											{
												label: "Duplicate",
												icon: <Copy />,
												onClick: () => {
													void handleDuplicate(trigger);
												},
											},
										]
									: []),
								{ separator: true as const },
								{
									label: "Delete",
									icon: <Trash2 />,
									destructive: true,
									onClick: () => {
										void handleDelete(trigger.id);
									},
								},
							]}
						/>
					</div>
				) : null,
		},
	];

	const bulkControls = (
		<>
			<BulkActionBar
				selectedCount={selection.selectedCount}
				totalCount={manageableTriggerIds.length}
				allSelected={selection.allSelected}
				someSelected={selection.someSelected}
				onToggleAll={selection.toggleAll}
				onClear={selection.clear}
				actionLabel="Delete"
				onAction={() => {
					setBulkOpen(true);
				}}
				showWhenEmpty={mode === "cards"}
			/>
			<BulkConfirmDialog
				open={bulkOpen}
				onOpenChange={setBulkOpen}
				title="Delete selected triggers?"
				description="Their configurations will be removed permanently. Existing run history is unaffected."
				items={selectedTriggers.map((trigger) => ({
					id: trigger.id,
					name: trigger.name,
				}))}
				confirmLabel="Delete"
				busyLabel="Deleting…"
				onConfirm={async (items) => {
					const results = await Promise.allSettled(
						items.map((item) => deleteTrigger(item.id)),
					);
					const succeeded: string[] = [];
					const failures: BulkFailure[] = [];
					results.forEach((result, index) => {
						const item = items.at(index);
						if (!item) return;
						if (result.status === "fulfilled") succeeded.push(item.id);
						else
							failures.push({
								id: item.id,
								name: item.name,
								message: getApiErrorMessage(result.reason, "Delete failed."),
							});
					});
					selection.remove(succeeded);
					return failures;
				}}
			/>
		</>
	);

	if (!isInitialized) {
		return mode === "table" ? (
			<DataTable
				columns={columns}
				rows={[]}
				rowKey={(trigger) => trigger.id}
				isLoading
				scrollBody
				minTableWidth="980px"
				bleedOnNarrow
			/>
		) : null;
	}

	if (triggers.length === 0) {
		return (
			<div className="flex flex-col items-center justify-center gap-4 rounded-2xl border border-dashed border-[#D7E0DB] dark:border-white/10 py-20">
				<div className="flex items-center justify-center size-12 rounded-2xl bg-[#EDF4F0] dark:bg-emerald-950/40">
					<AlarmClock className="size-6 text-[#3D8B63] dark:text-emerald-400" />
				</div>
				<div className="text-center">
					<p className="font-[family-name:var(--font-jakarta-sans)] text-[16px] font-bold text-[#1E2D28] dark:text-foreground">
						No triggers yet
					</p>
					<p className="mt-1 font-[family-name:var(--font-dm-sans)] text-[13.5px] text-[#6B7F76] dark:text-muted-foreground">
						Run an agent from a schedule or an external webhook.
					</p>
				</div>
				{canCreate && (
					<button
						type="button"
						onClick={() => {
							onCreate();
						}}
						className="inline-flex cursor-pointer items-center gap-1.5 rounded-[7px] bg-primary px-3.5 py-[7px] text-[12.5px] font-semibold text-primary-foreground transition-opacity hover:opacity-90"
					>
						<Plus className="size-4" />
						New trigger
					</button>
				)}
			</div>
		);
	}

	if (visibleTriggers.length === 0) {
		return (
			<div className="py-16 text-center font-[family-name:var(--font-dm-sans)] text-[13.5px] text-[#A3B5AD] dark:text-muted-foreground">
				{query ? (
					<>
						No trigger matches “{search}”.{" "}
						<button
							type="button"
							onClick={onClearSearch}
							className="cursor-pointer font-semibold text-petrol hover:underline dark:text-panel-terminal"
						>
							Clear search
						</button>
					</>
				) : scope !== "all" ? (
					"No trigger matches this visibility filter."
				) : view === "active" ? (
					"No active triggers."
				) : (
					"No paused triggers."
				)}
			</div>
		);
	}

	if (mode === "table") {
		return (
			<>
				{bulkControls}
				<DataTable
					columns={columns}
					rows={visibleTriggers}
					rowKey={(trigger) => trigger.id}
					isRowSelected={(trigger) => selection.isSelected(trigger.id)}
					selectionMode={selection.selectionMode}
					isRowSelectable={(trigger) => trigger.canManage}
					onRowSelectionClick={(trigger, shiftKey) => {
						selection.toggle(trigger.id, shiftKey);
					}}
					scrollBody
					minTableWidth="980px"
					bleedOnNarrow
					groupTree={{
						...groupTree,
						storageKey: `triggers:${view}:table-group`,
					}}
					onRowClick={(trigger) => {
						router.push(`/triggers/${trigger.id}`);
					}}
				/>
			</>
		);
	}

	return (
		<>
			{bulkControls}
			<GroupedCardTree
				tree={groupTree}
				storageKey={`triggers:${view}:card-group`}
				renderItem={(trigger) => (
					<TriggerCard
						key={trigger.id}
						trigger={trigger}
						selected={selection.isSelected(trigger.id)}
						selectionMode={selection.selectionMode}
						onToggleSelection={(shiftKey) => {
							selection.toggle(trigger.id, shiftKey);
						}}
						onDuplicate={(candidate) => {
							void handleDuplicate(candidate);
						}}
						canCreate={canCreate}
						onDelete={(id) => {
							void handleDelete(id);
						}}
					/>
				)}
			/>
		</>
	);
}
