"use client";

import { useEffect, useMemo, useState } from "react";
import { Bot, LoaderCircle } from "lucide-react";
import type { Agent } from "@/types/agents";
import { canConfigureAgent } from "@/types/agents";
import * as agentsApi from "@/lib/api/resources/agents";
import type { UnderlineTab } from "@/components/ui/underline-tabs";
import { SearchBar } from "@/components/ui/search-bar";
import AgentToolList from "@/app/(protected)/agents/[id]/components/agent-tool-list";
import AgentSkillList from "@/app/(protected)/agents/[id]/components/agent-skill-list";
import AgentSubagentList from "@/app/(protected)/agents/[id]/components/agent-subagent-list";
import { fromAgent } from "@/app/(protected)/agents/lib/agent-form";

export type TriggerResourceKind = "mcp" | "skills" | "subagents" | "sandbox";
export type TriggerRightTab = "frequency" | TriggerResourceKind;

const SEARCH_PLACEHOLDERS: Record<TriggerResourceKind, string> = {
	mcp: "Search MCP servers and tools",
	skills: "Search skills",
	subagents: "Search subagents",
	sandbox: "Search sandboxes",
};

export interface TriggerAgentState {
	agentId: string | null;
	agent: Agent | null;
	isLoading: boolean;
	failed: boolean;
}

/** Loads the trigger's agent once for every resource tab. */
export function useTriggerAgent(agentId: string | null): TriggerAgentState {
	const [result, setResult] = useState<{
		agentId: string;
		agent: Agent | null;
		failed: boolean;
	} | null>(null);

	useEffect(() => {
		if (!agentId) return;
		let active = true;
		void agentsApi
			.getAgent(agentId)
			.then((loadedAgent) => {
				if (!active) return;
				setResult({ agentId, agent: loadedAgent, failed: false });
			})
			.catch(() => {
				if (!active) return;
				setResult({ agentId, agent: null, failed: true });
			});
		return () => {
			active = false;
		};
	}, [agentId]);

	const current = result?.agentId === agentId ? result : null;
	return {
		agentId,
		agent: current?.agent ?? null,
		isLoading: Boolean(agentId && !current),
		failed: current?.failed ?? false,
	};
}

/** One tab per resource type, counted like the agent page's capability tabs. */
export function triggerResourceTabs(
	agent: Agent | null,
): UnderlineTab<TriggerResourceKind>[] {
	const form = agent ? fromAgent(agent) : null;
	return [
		{ key: "mcp", label: "MCP servers", count: form?.mcpServers.length },
		{ key: "skills", label: "Skills", count: form?.skillIds.length },
		{ key: "subagents", label: "Subagents", count: form?.subagentIds.length },
		{ key: "sandbox", label: "Sandbox", count: form?.sandboxes.length },
	];
}

interface TriggerResourcesProps {
	kind: TriggerResourceKind;
	agentState: TriggerAgentState;
	disabledMcpServerIds: string[] | null;
	disabledSkillIds: string[] | null;
	disabledSandboxIds: string[] | null;
	disabledSubagentIds: string[] | null;
	disabledMcpTools: Record<string, string[]> | null;
	readOnly?: boolean;
	onDisabledMcpServerIdsChange?: (ids: string[]) => void;
	onDisabledSkillIdsChange?: (ids: string[]) => void;
	onDisabledSandboxIdsChange?: (ids: string[]) => void;
	onDisabledSubagentIdsChange?: (ids: string[]) => void;
	onDisabledMcpToolsChange?: (tools: Record<string, string[]>) => void;
}

function isEnabled(
	resourceId: string,
	disabledIds: string[] | null,
	enabledByDefault?: boolean,
): boolean {
	return disabledIds === null
		? enabledByDefault !== false
		: !disabledIds.includes(resourceId);
}

export default function TriggerResources({
	kind,
	agentState,
	disabledMcpServerIds,
	disabledSkillIds,
	disabledSandboxIds,
	disabledSubagentIds,
	disabledMcpTools,
	readOnly = false,
	onDisabledMcpServerIdsChange,
	onDisabledSkillIdsChange,
	onDisabledSandboxIdsChange,
	onDisabledSubagentIdsChange,
	onDisabledMcpToolsChange,
}: TriggerResourcesProps) {
	const { agentId, agent, isLoading, failed } = agentState;
	const agentForm = useMemo(() => (agent ? fromAgent(agent) : null), [agent]);
	const [search, setSearch] = useState<{
		kind: TriggerResourceKind;
		query: string;
	}>({ kind, query: "" });
	// Scoped to the tab it was typed in, so switching tabs starts from a clear field.
	const query = search.kind === kind ? search.query : "";
	const mcpServers = useMemo(
		() =>
			(agentForm?.mcpServers ?? []).map((server) => ({
				...server,
				enabledByDefault: isEnabled(
					server.mcpServerId,
					disabledMcpServerIds,
					server.enabledByDefault,
				),
			})),
		[agentForm, disabledMcpServerIds],
	);
	const sandboxes = useMemo(
		() =>
			(agentForm?.sandboxes ?? []).map((sandbox) => ({
				...sandbox,
				enabledByDefault: isEnabled(
					sandbox.sandboxId,
					disabledSandboxIds,
					sandbox.enabledByDefault,
				),
			})),
		[agentForm, disabledSandboxIds],
	);
	const disabledSkills =
		disabledSkillIds ?? agentForm?.disabledSkillIdsByDefault ?? [];
	const disabledSubagents =
		disabledSubagentIds ?? agentForm?.disabledSubagentIdsByDefault ?? [];
	const effectiveDisabledMcpTools = useMemo(() => {
		if (disabledMcpTools !== null) return disabledMcpTools;
		return Object.fromEntries(
			(agentForm?.mcpServers ?? []).map((server) => [
				server.mcpServerId,
				Object.entries(server.tools ?? {})
					.filter(([, status]) => status === "needs_approval")
					.map(([toolName]) => toolName),
			]),
		);
	}, [agentForm, disabledMcpTools]);

	if (!agentId) {
		return (
			<div className="flex min-h-[280px] flex-col items-center justify-center rounded-xl border border-dashed border-input/80 px-6 text-center">
				<span className="flex size-10 items-center justify-center rounded-xl bg-card text-meta shadow-sm dark:bg-white/5 dark:text-panel-dim">
					<Bot className="size-5" />
				</span>
				<p className="mt-3 text-[13px] font-semibold text-foreground">
					Select an agent first
				</p>
				<p className="mt-1 max-w-[260px] text-[11.5px] leading-5 text-meta dark:text-panel-dim">
					Its allowed tools, sandbox, skills and subagents will appear here.
				</p>
			</div>
		);
	}

	if (isLoading) {
		return (
			<div className="flex min-h-[280px] items-center justify-center gap-2 text-[12.5px] text-meta dark:text-panel-dim">
				<LoaderCircle className="size-4 animate-spin" />
				Loading agent resources…
			</div>
		);
	}

	if (failed) {
		return (
			<div className="rounded-[10px] bg-destructive/10 px-4 py-3 text-[12.5px] font-medium text-destructive">
				Could not load this agent&apos;s resources.
			</div>
		);
	}
	if (!agent || !agentForm) return null;

	const itemCount = {
		mcp: agentForm.mcpServers.length,
		skills: agentForm.skillIds.length,
		subagents: agentForm.subagentIds.length,
		sandbox: agentForm.sandboxes.length,
	}[kind];

	const list =
		kind === "mcp" || kind === "sandbox" ? (
			<AgentToolList
				key={`${agent.id}:${kind}`}
				agentId={agent.id}
				readOnly
				query={query}
				canToggleDefault={!readOnly}
				mode="trigger"
				resourceKind={kind}
				triggerToolsReadOnly={readOnly}
				canEdit={canConfigureAgent(agent.currentUserPermission)}
				mcpServers={mcpServers}
				sandboxes={sandboxes}
				triggerDisabledTools={effectiveDisabledMcpTools}
				onMcpServersChange={(update) => {
					const next = update(mcpServers);
					onDisabledMcpServerIdsChange?.(
						next
							.filter((server) => server.enabledByDefault === false)
							.map((server) => server.mcpServerId),
					);
				}}
				onSandboxesChange={(next) => {
					onDisabledSandboxIdsChange?.(
						next
							.filter((sandbox) => sandbox.enabledByDefault === false)
							.map((sandbox) => sandbox.sandboxId),
					);
				}}
				onTriggerToolEnabledChange={(serverId, toolName, enabled) => {
					const rejected = new Set(
						effectiveDisabledMcpTools[serverId] ?? [],
					);
					if (enabled) rejected.delete(toolName);
					else rejected.add(toolName);
					onDisabledMcpToolsChange?.({
						...effectiveDisabledMcpTools,
						[serverId]: [...rejected],
					});
				}}
			/>
		) : kind === "skills" ? (
			<div key={agent.id} className="[&>div]:mt-0">
				<AgentSkillList
					readOnly
					query={query}
					canToggleDefault={!readOnly}
					mode="trigger"
					skillIds={agentForm.skillIds}
					disabledByDefaultIds={disabledSkills}
					fallbackSkills={agent.skills ?? []}
					runsCode={sandboxes.length > 0}
					onDefaultEnabledChange={(skillId, enabled) => {
						onDisabledSkillIdsChange?.(
							enabled
								? disabledSkills.filter((id) => id !== skillId)
								: [...new Set([...disabledSkills, skillId])],
						);
					}}
				/>
			</div>
		) : (
			<div key={agent.id} className="[&>div]:mt-0">
				<AgentSubagentList
					readOnly
					query={query}
					canToggleDefault={!readOnly}
					mode="trigger"
					agentId={agent.id}
					isSubagent={agent.isSubagent}
					subagentIds={agentForm.subagentIds}
					disabledByDefaultIds={disabledSubagents}
					fallbackSubagents={agent.subagents}
					onDefaultEnabledChange={(subagentId, enabled) => {
						onDisabledSubagentIdsChange?.(
							enabled
								? disabledSubagents.filter((id) => id !== subagentId)
								: [...new Set([...disabledSubagents, subagentId])],
						);
					}}
				/>
			</div>
		);

	return (
		<>
			{itemCount > 0 && (
				<SearchBar
					placeholder={SEARCH_PLACEHOLDERS[kind]}
					value={query}
					onChange={(next) => {
						setSearch({ kind, query: next });
					}}
					className="mb-5"
				/>
			)}
			{list}
		</>
	);
}
