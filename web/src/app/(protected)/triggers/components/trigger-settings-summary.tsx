"use client";

import { useEffect } from "react";
import { Trigger } from "@/types/triggers";
import { useProjectsStore } from "@/stores/projects-store";
import { getProjectFolderPath } from "@/lib/project-folders";

interface TriggerSettingsSummaryProps {
	trigger: Trigger;
}

function SettingRow({
	label,
	children,
}: {
	label: string;
	children: React.ReactNode;
}) {
	return (
		<div className="flex items-center justify-between gap-4 px-4 py-2.5">
			<span className="shrink-0 text-[12.5px] text-meta dark:text-panel-dim">
				{label}
			</span>
			<span className="min-w-0 truncate text-right text-[12.5px] font-medium text-foreground">
				{children}
			</span>
		</div>
	);
}

function ToggleState({ enabled }: { enabled: boolean }) {
	return (
		<span className="inline-flex items-center gap-1.5">
			<span
				className={`size-1.5 rounded-full ${
					enabled ? "bg-success dark:bg-emerald-400" : "bg-faint dark:bg-white/20"
				}`}
			/>
			<span className={enabled ? "" : "text-meta dark:text-panel-dim"}>
				{enabled ? "On" : "Off"}
			</span>
		</span>
	);
}

/** Read-only recap of the options set in the trigger editor. */
export default function TriggerSettingsSummary({
	trigger,
}: TriggerSettingsSummaryProps) {
	const projects = useProjectsStore((state) => state.projects);
	const projectTree = useProjectsStore((state) => state.tree);
	const fetchProjects = useProjectsStore((state) => state.fetchProjects);

	useEffect(() => {
		if (trigger.projectId) void fetchProjects().catch(() => {});
	}, [fetchProjects, trigger.projectId]);

	const project = projects.find((p) => p.id === trigger.projectId);
	const folders =
		projectTree.find((p) => p.id === trigger.projectId)?.folders ?? [];
	const folder = folders.find((f) => f.id === trigger.folderId);

	const projectLabel = trigger.projectId
		? [
				project
					? project.emoji
						? `${project.emoji} ${project.name}`
						: project.name
					: "Linked project",
				folder ? getProjectFolderPath(folder, folders) : null,
			]
				.filter(Boolean)
				.join(" / ")
		: null;

	return (
		<div className="flex flex-col divide-y divide-hairline rounded-[10px] border border-border bg-card dark:divide-white/5">
			<SettingRow label="Group">
				{trigger.group ?? (
					<span className="text-meta dark:text-panel-dim">None</span>
				)}
			</SettingRow>
			<SettingRow label="Project">
				{projectLabel ?? (
					<span className="text-meta dark:text-panel-dim">None</span>
				)}
			</SettingRow>
			<SettingRow label="Push notifications">
				<ToggleState enabled={trigger.notificationsEnabled} />
			</SettingRow>
			<SettingRow label="Run once">
				<ToggleState enabled={trigger.runOnce} />
			</SettingRow>
			<SettingRow label="Complete automatically">
				<ToggleState enabled={trigger.autoComplete} />
			</SettingRow>
		</div>
	);
}
