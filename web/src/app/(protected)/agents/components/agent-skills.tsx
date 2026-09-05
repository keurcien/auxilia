"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api/client";
import { getApiErrorMessage } from "@/lib/api/errors";
import { Agent } from "@/types/agents";
import { Skill, SkillAttachment } from "@/types/skills";

export default function AgentSkills({
	agent,
	canEdit,
}: {
	agent: Agent;
	canEdit: boolean;
}) {
	const [library, setLibrary] = useState<Skill[]>([]);
	const [attached, setAttached] = useState<SkillAttachment[]>([]);
	const [error, setError] = useState("");
	const [busy, setBusy] = useState(false);
	const load = useCallback(async () => {
		const [a, b] = await Promise.all([
			api.get<Skill[]>("/skills"),
			api.get<SkillAttachment[]>(`/agents/${agent.id}/skills`),
		]);
		setLibrary(a.data);
		setAttached(b.data);
	}, [agent.id]);
	useEffect(() => {
		void Promise.resolve()
			.then(load)
			.catch((e) => {
				setError(getApiErrorMessage(e, "Could not load agent skills"));
			});
	}, [load]);
	async function change(skillId: string, versionId: string) {
		setBusy(true);
		setError("");
		try {
			if (versionId)
				await api.put(`/agents/${agent.id}/skills/${skillId}`, { versionId });
			else await api.delete(`/agents/${agent.id}/skills/${skillId}`);
			await load();
		} catch (e) {
			setError(getApiErrorMessage(e, "Could not update skill"));
		} finally {
			setBusy(false);
		}
	}
	return (
		<section className="mt-6 space-y-3 border-t pt-5">
			<div className="flex justify-between">
				<h3 className="font-semibold">Skills</h3>
				<Link className="text-sm text-primary" href="/skills">
					Manage library
				</Link>
			</div>
			<p className="text-sm text-muted-foreground">
				Reusable procedures. Changes here save immediately.
			</p>
			{error && (
				<p role="alert" className="text-sm text-destructive">
					{error}
				</p>
			)}
			{library
				.filter((s) => canEdit || attached.some((a) => a.skillId === s.id))
				.map((s) => {
					const binding = attached.find((a) => a.skillId === s.id);
					return (
						<div key={s.id} className="rounded-lg border p-3">
							<Link className="text-sm font-medium" href={`/skills/${s.id}`}>
								{s.draft.title}
							</Link>
							<p className="my-2 text-xs text-muted-foreground">
								{s.draft.description}
							</p>
							<select
								aria-label={`Skill version: ${s.draft.title}`}
								className="w-full rounded border bg-background p-2 text-sm"
								value={binding?.versionId ?? ""}
								disabled={!canEdit || busy}
								onChange={(e) => {
									void change(s.id, e.target.value);
								}}
							>
								<option value="">Not attached</option>
								{s.versions.map((v) => {
									const missing = [
										...(v.bundle.requiresCode && !agent.sandboxes.length
											? ["code execution"]
											: []),
										...(v.bundle.requiredMcpServerIds.some(
											(id) =>
												!agent.mcpServers.some((m) => m.mcpServerId === id),
										)
											? ["MCP connection"]
											: []),
									];
									return (
										<option
											key={v.id}
											value={v.id}
											disabled={missing.length > 0}
										>
											v{v.number} —{" "}
											{missing.length ? `Needs ${missing.join(", ")}` : "Ready"}
										</option>
									);
								})}
							</select>
							{!s.versions.length && (
								<p className="mt-2 text-xs text-muted-foreground">
									Publish a version to attach it.
								</p>
							)}
							{binding?.missing.length ? (
								<p className="text-sm text-destructive">
									Needs {binding.missing.join(", ")}
								</p>
							) : null}
						</div>
					);
				})}
			{!library.length && (
				<p className="text-sm text-muted-foreground">
					No skills yet. Create one in the library or ask an agent to save a
					routine.
				</p>
			)}
		</section>
	);
}
