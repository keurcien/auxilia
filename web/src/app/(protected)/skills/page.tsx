"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api/client";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
	WorkspacePage,
	WorkspaceTopBarButton,
} from "@/components/layout/workspace-page";
import { Skill } from "@/types/skills";

export default function SkillsPage() {
	const [skills, setSkills] = useState<Skill[]>([]);
	const [query, setQuery] = useState("");
	const [error, setError] = useState("");
	const [loading, setLoading] = useState(true);
	const router = useRouter();
	useEffect(() => {
		void api
			.get<Skill[]>("/skills")
			.then((r) => {
				setSkills(r.data);
			})
			.catch((e) => {
				setError(getApiErrorMessage(e, "Could not load skills"));
			})
			.finally(() => {
				setLoading(false);
			});
	}, []);
	async function upload(file: File) {
		const data = new FormData();
		data.append("file", file);
		try {
			const result = await api.post<Skill>("/skills/import", data);
			router.push(`/skills/${result.data.id}`);
		} catch (e) {
			setError(getApiErrorMessage(e, "Import failed"));
		}
	}
	return (
		<WorkspacePage
			slug="skills"
			title="Skills"
			intro="Teach your agents how your team works. Save reusable procedures, scripts and templates, then try them before publishing."
			search={{
				placeholder: "Search skills…",
				value: query,
				onChange: setQuery,
			}}
			actions={
				<>
					<label className="cursor-pointer text-sm">
						Import bundle
						<input
							type="file"
							accept=".md,.zip,.skill"
							className="sr-only"
							onChange={(e) => {
								const file = e.target.files?.[0];
								if (file) void upload(file);
							}}
						/>
					</label>
					<WorkspaceTopBarButton
						onClick={() => {
							router.push("/skills/new");
						}}
					>
						Create skill
					</WorkspaceTopBarButton>
				</>
			}
		>
			{error && (
				<p role="alert" className="text-destructive">
					{error}
				</p>
			)}
			{loading ? (
				<p>Loading skills…</p>
			) : skills.length === 0 ? (
				<div className="rounded-xl border border-dashed p-10 text-center">
					<p className="font-medium">Turn a successful task into a skill</p>
					<p className="mt-2 text-muted-foreground">
						Ask any agent: “Save this procedure as a reusable skill.” Or create
						one here.
					</p>
				</div>
			) : (
				<div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
					{skills
						.filter((s) =>
							`${s.draft.title} ${s.draft.description}`
								.toLowerCase()
								.includes(query.toLowerCase()),
						)
						.map((s) => (
							<Link
								key={s.id}
								href={`/skills/${s.id}`}
								className="rounded-xl border bg-card p-5 transition-colors hover:border-primary"
							>
								<div className="flex justify-between gap-3">
									<h2 className="font-semibold">{s.draft.title}</h2>
									<span className="text-xs text-muted-foreground">
										{s.visibility}
									</span>
								</div>
								<p className="mt-2 text-sm text-muted-foreground">
									{s.draft.description}
								</p>
								<div className="mt-5 flex gap-3 text-xs">
									<span>
										{s.versions.length
											? `Published v${s.versions[0].number}`
											: "Draft"}
									</span>
									<span>
										{s.draft.requiresCode
											? "Needs code execution"
											: "Instructions"}
									</span>
									<span>{s.draft.files.length} files</span>
								</div>
							</Link>
						))}
				</div>
			)}
		</WorkspacePage>
	);
}
