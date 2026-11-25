"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { useScopeChangePlanner } from "@/components/sharing/scope-plan-dialog";
import { VisibilityPicker } from "@/components/ui/visibility-picker";
import { getApiErrorMessage } from "@/lib/api/errors";
import { useProjectsStore } from "@/stores/projects-store";
import type { Project } from "@/types/projects";
import type { ResourceVisibility } from "@/types/visibility";

interface Scope {
	visibility: ResourceVisibility;
	teamIds: string[];
}

function sameScope(a: Scope, b: Scope): boolean {
	return (
		a.visibility === b.visibility &&
		[...a.teamIds].sort().join(",") === [...b.teamIds].sort().join(",")
	);
}

/**
 * Saves a project's visibility as soon as it is picked (team selections when
 * the picker closes). A change that needs the project's agents, or their MCP
 * servers and skills, shared too opens the access plan first.
 */
export function ProjectVisibilityEditor({
	project,
}: {
	project: Pick<Project, "id" | "visibility" | "teamIds">;
}) {
	const updateProject = useProjectsStore((state) => state.updateProject);
	const fetchProjects = useProjectsStore((state) => state.fetchProjects);
	const refreshProjectDetail = useProjectsStore(
		(state) => state.refreshProjectDetail,
	);
	const { requestScopeChange, dialog } = useScopeChangePlanner();
	const [scope, setScope] = useState<Scope>({
		visibility: project.visibility,
		teamIds: project.teamIds,
	});
	const [saving, setSaving] = useState(false);
	const committedRef = useRef<Scope>(scope);
	const draftRef = useRef<Scope>(scope);

	useEffect(() => {
		const next = { visibility: project.visibility, teamIds: project.teamIds };
		setScope(next);
		committedRef.current = next;
		draftRef.current = next;
	}, [project.teamIds, project.visibility]);

	const resetToCommitted = () => {
		setScope(committedRef.current);
		draftRef.current = committedRef.current;
	};

	const save = async (next: Scope) => {
		if (sameScope(next, committedRef.current)) return;
		if (next.visibility === "teams" && next.teamIds.length === 0) {
			resetToCommitted();
			return;
		}
		setSaving(true);
		try {
			const outcome = await requestScopeChange({
				kind: "project",
				id: project.id,
				...next,
			});
			if (outcome === "cancelled") {
				resetToCommitted();
				return;
			}
			if (outcome === "proceed") {
				await updateProject(project.id, next);
			} else {
				await Promise.allSettled([
					fetchProjects(),
					refreshProjectDetail(project.id),
				]);
			}
			committedRef.current = next;
		} catch (error) {
			resetToCommitted();
			toast.error(
				getApiErrorMessage(error, "The project visibility could not be saved."),
			);
		} finally {
			setSaving(false);
		}
	};

	return (
		<div className="flex items-center gap-1">
			<VisibilityPicker
				compact
				visibility={scope.visibility}
				teamIds={scope.teamIds}
				onChange={(visibility, teamIds) => {
					const next = { visibility, teamIds };
					setScope(next);
					draftRef.current = next;
					if (visibility !== "teams") void save(next);
				}}
				onOpenChange={(open) => {
					if (!open && draftRef.current.visibility === "teams") {
						void save(draftRef.current);
					}
				}}
			/>
			{saving && (
				<Loader2
					aria-label="Saving project visibility"
					className="size-3.5 animate-spin text-meta"
				/>
			)}
			{dialog}
		</div>
	);
}
