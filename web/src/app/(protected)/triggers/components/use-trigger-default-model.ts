"use client";

import { useEffect, useState } from "react";
import * as agentsApi from "@/lib/api/resources/agents";
import { getDefaultModel } from "@/lib/utils/get-default-model";
import { useModelsStore } from "@/stores/models-store";

interface AgentModelDefaults {
	agentId: string;
	modelId: string | null;
	reasoningEffort: string | null;
}

export interface TriggerDefaultModel {
	/** "Agent default" when the agent pins an available model, else
	 * "Workspace default". */
	label: string;
	modelId: string | null;
	reasoningEffort: string | null;
}

/** What a trigger without a model runs on: the agent's default model and
 * effort while that model is available, else the workspace default model at
 * its default effort. Mirrors the backend resolution of a new conversation. */
export function useTriggerDefaultModel(
	agentId: string | null,
): TriggerDefaultModel {
	const models = useModelsStore((state) => state.models);
	const [agentDefaults, setAgentDefaults] =
		useState<AgentModelDefaults | null>(null);

	useEffect(() => {
		if (!agentId) return;
		let cancelled = false;
		agentsApi
			.getAgent(agentId)
			.then((agent) => {
				if (cancelled) return;
				setAgentDefaults({
					agentId,
					modelId: agent.defaultModelId ?? null,
					reasoningEffort: agent.defaultReasoningEffort ?? null,
				});
			})
			.catch(() => {
				// Without the agent's defaults the workspace default is shown.
			});
		return () => {
			cancelled = true;
		};
	}, [agentId]);

	const current = agentDefaults?.agentId === agentId ? agentDefaults : null;
	const agentModel = current?.modelId
		? models.find((model) => model.id === current.modelId)
		: undefined;
	if (agentModel) {
		const effort = current?.reasoningEffort ?? null;
		return {
			label: "Agent default",
			modelId: agentModel.id,
			reasoningEffort:
				effort && agentModel.reasoningEffortLevels.includes(effort)
					? effort
					: null,
		};
	}
	return {
		label: "Workspace default",
		modelId: getDefaultModel(models) ?? null,
		reasoningEffort: null,
	};
}
