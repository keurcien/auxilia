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
			.catch((e) => setError(getApiErrorMessage(e, "Could not load skills")));
	}, [load]);
	async function change(id: string, enabled: boolean) {
		setBusy(true);
		setError("");
		try {
			if (enabled) await api.put(`/agents/${agent.id}/skills/${id}`);
			else await api.delete(`/agents/${agent.id}/skills/${id}`);
			await load();
		} catch (e) {
			setError(getApiErrorMessage(e, "Could not update skills"));
		} finally {
			setBusy(false);
		}
	}
	return (
		<section className="mt-6 space-y-3 border-t pt-5">
			<div className="flex justify-between">
				<h3 className="font-semibold">Skills</h3>
				<Link href="/skills" className="text-sm text-primary">
					Manage skills
				</Link>
			</div>
			<p className="text-sm text-muted-foreground">
				Enable reusable instructions and scripts. Scripts need a connected
				sandbox to run.
			</p>
			{error && (
				<p role="alert" className="text-sm text-destructive">
					{error}
				</p>
			)}
			{library
				.filter((s) => canEdit || attached.some((a) => a.skillId === s.id))
				.map((s) => (
					<label
						key={s.id}
						className="flex items-start gap-3 rounded-lg border p-3"
					>
						<input
							type="checkbox"
							aria-label={`Enable ${s.name}`}
							className="mt-1"
							checked={attached.some((a) => a.skillId === s.id)}
							disabled={!canEdit || busy}
							onChange={(e) => void change(s.id, e.target.checked)}
						/>
						<span>
							<Link href={`/skills/${s.id}`} className="text-sm font-medium">
								{s.name}
							</Link>
							<span className="block text-xs text-muted-foreground">
								{s.description}
							</span>
						</span>
					</label>
				))}
			{!library.length && (
				<p className="text-sm text-muted-foreground">
					No skills yet. Create one in the library.
				</p>
			)}
		</section>
	);
}
