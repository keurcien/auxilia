/**
 * Sharing resource — `/sharing/`. Plans an access change across the resources
 * it depends on (project, trigger, agent, MCP servers, skills) and applies a
 * whole plan in one transaction.
 */
import { api } from "@/lib/api/client";
import type { ScopeChange, ScopePlan } from "@/types/sharing";

export async function planScopeChange(change: ScopeChange): Promise<ScopePlan> {
	const response = await api.post<ScopePlan>("/sharing/plan", change);
	return response.data;
}

export async function applyScopeChanges(changes: ScopeChange[]): Promise<void> {
	await api.post("/sharing/apply", { changes });
}
