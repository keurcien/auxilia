"use client";

import { useCallback } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { getApiErrorMessage } from "@/lib/api/errors";
import * as agentsApi from "@/lib/api/resources/agents";
import { useAgentsStore } from "@/stores/agents-store";

/** Copies an agent's last saved configuration and image, then opens the copy. */
export function useDuplicateAgent() {
	const router = useRouter();
	const createAgent = useAgentsStore((state) => state.createAgent);
	const updateAgent = useAgentsStore((state) => state.updateAgent);

	return useCallback(
		async (agentId: string) => {
			try {
				const source = await agentsApi.getAgent(agentId);
				let created = await createAgent({
					name: `${source.name} copy`,
					instructions: source.instructions ?? "",
					description: source.description ?? null,
					group: source.group ?? null,
					emoji: source.emoji ?? null,
					color: source.color ?? null,
					visibility: source.visibility,
					webSearchEnabled: source.webSearchEnabled ?? false,
					toolDiscoveryMode: source.toolDiscoveryMode ?? "lazy",
					defaultModelId: source.defaultModelId ?? null,
					defaultReasoningEffort: source.defaultReasoningEffort ?? null,
					teamIds: source.teamIds,
					mcpServers: source.mcpServers.map((server) => ({
						mcpServerId: server.mcpServerId,
						enabledByDefault: server.enabledByDefault ?? true,
						tools: server.tools ?? null,
					})),
					sandboxes: (source.sandboxes ?? []).map((sandbox) => ({
						sandboxId: sandbox.sandboxId,
						enabledByDefault: sandbox.enabledByDefault ?? true,
						tools: sandbox.tools,
					})),
					subagentIds: source.subagents.map((subagent) => subagent.id),
					disabledSubagentIdsByDefault: source.subagents
						.filter((subagent) => subagent.enabledByDefault === false)
						.map((subagent) => subagent.id),
					skillIds: (source.skills ?? []).map((skill) => skill.id),
					disabledSkillIdsByDefault: (source.skills ?? [])
						.filter((skill) => skill.enabledByDefault === false)
						.map((skill) => skill.id),
				});
				let imageCopyFailed = false;
				if (source.imageRevision) {
					try {
						const response = await fetch(
							agentsApi.agentImageUrl(source.id, source.imageRevision),
						);
						if (!response.ok) throw new Error("Could not read the agent image.");
						const blob = await response.blob();
						const image = new File([blob], "agent-image", {
							type: blob.type || "image/png",
						});
						const revision = await agentsApi.uploadAgentImage(created.id, image);
						created = { ...created, imageRevision: revision };
						updateAgent(created.id, created);
					} catch {
						imageCopyFailed = true;
					}
				}
				if (imageCopyFailed) {
					toast.warning(
						`Duplicated as “${created.name}”, but its image could not be copied.`,
					);
				} else {
					toast.success(`Duplicated as “${created.name}”.`);
				}
				router.push(`/agents/${created.id}`);
			} catch (error: unknown) {
				toast.error(getApiErrorMessage(error, "Could not duplicate the agent."));
			}
		},
		[createAgent, router, updateAgent],
	);
}
