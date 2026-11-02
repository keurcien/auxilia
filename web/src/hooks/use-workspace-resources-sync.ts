"use client";

import { useEffect } from "react";

import { useAgentsStore } from "@/stores/agents-store";
import { useMcpServersStore } from "@/stores/mcp-servers-store";
import { useProjectsStore } from "@/stores/projects-store";
import { useSkillsStore } from "@/stores/skills-store";
import { useTriggersStore } from "@/stores/triggers-store";
import { useWorkspaceEventsStore } from "@/stores/workspace-events-store";

const reportRefreshError = (resource: string, error: unknown) => {
	console.error(`Failed to refresh ${resource} after a workspace event:`, error);
};

export function useWorkspaceResourcesSync(): void {
	const agentsVersion = useWorkspaceEventsStore(
		(state) => state.agentsVersion,
	);
	const triggersVersion = useWorkspaceEventsStore(
		(state) => state.triggersVersion,
	);
	const mcpServersVersion = useWorkspaceEventsStore(
		(state) => state.mcpServersVersion,
	);
	const skillsVersion = useWorkspaceEventsStore(
		(state) => state.skillsVersion,
	);
	const projectsVersion = useWorkspaceEventsStore(
		(state) => state.projectsVersion,
	);

	useEffect(() => {
		if (agentsVersion === 0) return;
		void useAgentsStore
			.getState()
			.refreshAgents()
			.catch((error: unknown) => {
				reportRefreshError("agents", error);
			});
	}, [agentsVersion]);

	useEffect(() => {
		if (triggersVersion === 0) return;
		void useTriggersStore
			.getState()
			.refreshTriggers()
			.catch((error: unknown) => {
				reportRefreshError("triggers", error);
			});
	}, [triggersVersion]);

	useEffect(() => {
		if (mcpServersVersion === 0) return;
		void useMcpServersStore
			.getState()
			.refreshMcpServers()
			.catch((error: unknown) => {
				reportRefreshError("MCP servers", error);
			});
	}, [mcpServersVersion]);

	useEffect(() => {
		if (projectsVersion === 0) return;
		const projects = useProjectsStore.getState();
		const mountedProjectIds = Object.keys(projects.mountedDetailIds);
		void projects
			.refreshTree()
			.then(async () => {
				const current = useProjectsStore.getState();
				const results = await Promise.allSettled(
					mountedProjectIds
						.filter((id) =>
							current.tree.some((project) => project.id === id),
						)
						.map((id) => current.refreshProjectDetail(id)),
				);
				for (const result of results) {
					if (result.status === "rejected") {
						reportRefreshError("projects", result.reason);
					}
				}
			})
			.catch((error: unknown) => {
				reportRefreshError("projects", error);
			});
	}, [projectsVersion]);

	useEffect(() => {
		if (skillsVersion === 0) return;
		const projects = useProjectsStore.getState();
		void Promise.allSettled([
			useSkillsStore.getState().fetchSkills(true),
			useSkillsStore.getState().fetchSources(true),
			...Object.keys(projects.mountedDetailIds)
				.filter((id) => projects.detailsById[id])
				.map((id) => projects.refreshProjectDetail(id)),
		]).then((results) => {
			for (const result of results) {
				if (result.status === "rejected") {
					reportRefreshError("skills", result.reason);
				}
			}
		});
	}, [skillsVersion]);
}
