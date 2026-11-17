"use client";

import { useEffect } from "react";
import Link from "next/link";
import { Trigger } from "@/types/triggers";
import { useProjectsStore } from "@/stores/projects-store";
import { getProjectFolderPath } from "@/lib/project-folders";
import { Switch } from "@/components/ui/switch";

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

function ToggleState({ label, enabled }: { label: string; enabled: boolean }) {
	return (
		<Switch
			checked={enabled}
			disabled
			aria-label={label}
			className="align-middle disabled:cursor-default disabled:opacity-100"
		/>
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
				{projectLabel && trigger.projectId ? (
					<Link
						href={
							trigger.folderId
								? `/projects/${trigger.projectId}?folder=${trigger.folderId}`
								: `/projects/${trigger.projectId}`
						}
						className="text-petrol underline-offset-2 hover:underline dark:text-panel-terminal"
					>
						{projectLabel}
					</Link>
				) : (
					<span className="text-meta dark:text-panel-dim">None</span>
				)}
			</SettingRow>
			<SettingRow label="Push notifications">
				<ToggleState
					label="Push notifications"
					enabled={trigger.notificationsEnabled}
				/>
			</SettingRow>
			<SettingRow label="Run once">
				<ToggleState label="Run once" enabled={trigger.runOnce} />
			</SettingRow>
			<SettingRow label="Complete automatically">
				<ToggleState
					label="Complete automatically"
					enabled={trigger.autoComplete}
				/>
			</SettingRow>
		</div>
	);
}
