"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
	Dialog,
	DialogButton,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { AgentMultiPicker } from "@/components/editor/agent-multi-picker";
import { getApiErrorMessage } from "@/lib/api/errors";
import { audienceContains, type Audience } from "@/lib/audience";
import {
	attachToAgent,
	type AttachableResource,
} from "@/lib/api/resources/agents";
import { useAgentsStore } from "@/stores/agents-store";
import { useSkillsStore } from "@/stores/skills-store";
import { useUserStore } from "@/stores/user-store";
import { canConfigureAgent, type Agent } from "@/types/agents";

const COPY: Record<
	AttachableResource,
	{ noun: string; description: (name: string) => string }
> = {
	mcpServer: {
		noun: "MCP server",
		description: (name) =>
			`The agents you pick can use the tools of ${name}. You can change this later from each agent.`,
	},
	skill: {
		noun: "skill",
		description: (name) =>
			`The agents you pick can follow ${name}. You can change this later from each agent.`,
	},
	subagent: {
		noun: "subagent",
		description: (name) =>
			`The agents you pick can delegate tasks to ${name}. You can change this later from each agent.`,
	},
};

/** `ownerId` defaults to the current user, who owns what they just created. */
export type AttachedResource = Audience & { id: string; name: string };

function isCandidate(
	agent: Agent,
	kind: AttachableResource,
	resource: AttachedResource,
): boolean {
	if (agent.isArchived || !canConfigureAgent(agent.currentUserPermission)) {
		return false;
	}
	// The backend refuses a resource more private than the agent using it.
	if (!audienceContains(agent, resource)) return false;
	if (kind === "mcpServer") {
		return !agent.mcpServers.some((server) => server.mcpServerId === resource.id);
	}
	if (kind === "subagent") {
		// Graphs are one level deep: an agent used as a subagent cannot supervise.
		return (
			agent.id !== resource.id &&
			!agent.isSubagent &&
			!agent.subagents.some((subagent) => subagent.id === resource.id)
		);
	}
	return true;
}

interface AddToAgentsDialogProps {
	kind: AttachableResource;
	resource: AttachedResource;
	/** Called once, when the dialog is done (added, skipped, or nothing to offer). */
	onDone: () => void;
}

/**
 * Offered right after a resource is created: enable it on one or more of the
 * agents the user can configure. Mount it only while it should be offered.
 */
export function AddToAgentsDialog({
	kind,
	resource,
	onDone,
}: AddToAgentsDialogProps) {
	const agents = useAgentsStore((state) => state.agents);
	const isInitialized = useAgentsStore((state) => state.isInitialized);
	const fetchAgents = useAgentsStore((state) => state.fetchAgents);
	const refreshAgent = useAgentsStore((state) => state.refreshAgent);
	const fetchSkills = useSkillsStore((state) => state.fetchSkills);
	const userId = useUserStore((state) => state.user?.id);

	const [selectedIds, setSelectedIds] = useState<string[]>([]);
	const [enabledByDefault, setEnabledByDefault] = useState(false);
	const [isSubmitting, setIsSubmitting] = useState(false);
	const [failures, setFailures] = useState<
		{ agentId: string; name: string; message: string }[]
	>([]);
	const [finished, setFinished] = useState(false);
	const doneRef = useRef(false);

	const candidates = useMemo(() => {
		const owned = { ...resource, ownerId: resource.ownerId ?? userId };
		return agents
			.filter((agent) => isCandidate(agent, kind, owned))
			.sort((a, b) => a.name.localeCompare(b.name));
	}, [agents, kind, resource, userId]);
	const nothingToOffer = isInitialized && candidates.length === 0;

	const finish = () => {
		if (doneRef.current) return;
		doneRef.current = true;
		setFinished(true);
		onDone();
	};

	useEffect(() => {
		fetchAgents().catch(() => {
			// surfaced by the store; with no agents there is nothing to offer
		});
	}, [fetchAgents]);

	useEffect(() => {
		if (nothingToOffer && !doneRef.current) {
			doneRef.current = true;
			onDone();
		}
	}, [nothingToOffer, onDone]);

	const handleSubmit = async () => {
		if (selectedIds.length === 0) return;
		setIsSubmitting(true);
		setFailures([]);
		const results = await Promise.allSettled(
			selectedIds.map((agentId) =>
				attachToAgent(agentId, kind, resource.id, { enabledByDefault }),
			),
		);
		const added = selectedIds.filter(
			(_, index) => results[index]?.status === "fulfilled",
		);
		const failed = selectedIds.flatMap((agentId, index) => {
			const result = results[index];
			if (result?.status !== "rejected") return [];
			return [
				{
					agentId,
					name: agents.find((agent) => agent.id === agentId)?.name ?? "Agent",
					message: getApiErrorMessage(result.reason, "Could not add it."),
				},
			];
		});

		await Promise.allSettled([
			...added.map((agentId) => refreshAgent(agentId)),
			...(kind === "subagent" && added.length > 0
				? [refreshAgent(resource.id)]
				: []),
			...(kind === "skill" && added.length > 0 ? [fetchSkills(true)] : []),
		]);
		setIsSubmitting(false);

		if (added.length > 0) {
			toast.success(
				`${resource.name} added to ${added.length} agent${added.length === 1 ? "" : "s"}.`,
			);
		}
		if (failed.length === 0) {
			finish();
			return;
		}
		setSelectedIds(failed.map((failure) => failure.agentId));
		setFailures(failed);
	};

	const copy = COPY[kind];

	return (
		<Dialog
			open={isInitialized && candidates.length > 0 && !finished}
			onOpenChange={(open) => {
				if (!open && !isSubmitting) finish();
			}}
		>
			<DialogContent className="sm:max-w-[520px]">
				<DialogHeader>
					<DialogTitle>Add {resource.name} to agents?</DialogTitle>
					<DialogDescription>{copy.description(resource.name)}</DialogDescription>
				</DialogHeader>

				<div className="flex flex-col gap-4">
					<div>
						<span className="mb-1.5 block text-[11px] font-semibold text-label dark:text-muted-foreground">
							Agents
						</span>
						<AgentMultiPicker
							agents={candidates}
							value={selectedIds}
							onChange={(ids) => {
								setSelectedIds(ids);
								setFailures([]);
							}}
							disabled={isSubmitting}
						/>
					</div>

					<div className="flex items-center gap-3 rounded-[10px] border border-border bg-card px-4 py-3">
						<div className="min-w-0 flex-1">
							<p className="text-[12.5px] font-semibold text-foreground">
								New conversations
							</p>
							<p className="mt-0.5 text-[11.5px] text-muted-foreground">
								Enable this {copy.noun} by default in new conversations
							</p>
						</div>
						<Switch
							checked={enabledByDefault}
							disabled={isSubmitting}
							onCheckedChange={setEnabledByDefault}
							aria-label={`Enable ${resource.name} by default in new conversations`}
						/>
					</div>

					{failures.length > 0 && (
						<div className="rounded-[10px] bg-destructive/10 px-4 py-3 text-[12.5px] text-destructive">
							<p className="font-semibold">
								Not added to {failures.length} agent
								{failures.length === 1 ? "" : "s"}:
							</p>
							<ul className="mt-1 space-y-0.5">
								{failures.map((failure) => (
									<li key={failure.agentId}>
										{failure.name}: {failure.message}
									</li>
								))}
							</ul>
						</div>
					)}
				</div>

				<DialogFooter>
					<DialogButton
						variant="outline"
						disabled={isSubmitting}
						onClick={finish}
					>
						{failures.length > 0 ? "Continue" : "Not now"}
					</DialogButton>
					<DialogButton
						disabled={isSubmitting || selectedIds.length === 0}
						onClick={() => {
							void handleSubmit();
						}}
					>
						{isSubmitting
							? "Adding…"
							: selectedIds.length === 0
								? "Add to agents"
								: failures.length > 0
									? "Retry"
									: `Add to ${selectedIds.length} agent${selectedIds.length === 1 ? "" : "s"}`}
					</DialogButton>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}
