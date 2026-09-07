"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api/client";
import { getApiErrorMessage } from "@/lib/api/errors";
import { Skill, SkillFile } from "@/types/skills";
import {
	WorkspacePage,
	WorkspaceTopBarButton,
} from "@/components/layout/workspace-page";

const initial = `---
name: greeting
description: Use when greeting a new customer.
---
Greet the customer warmly. Read scripts/greet.py if needed.
`;
const input = "w-full rounded-lg border bg-background px-3 py-2 text-sm";

export default function SkillEditor({ id }: { id?: string }) {
	const router = useRouter();
	const [skill, setSkill] = useState<Skill>();
	const [content, setContent] = useState(initial);
	const [files, setFiles] = useState<SkillFile[]>([]);
	const [visibility, setVisibility] = useState<"private" | "workspace">(
		"private",
	);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState("");
	const [notice, setNotice] = useState("");
	const editable = !id || !!skill?.canEdit;
	const dirty =
		!skill ||
		content !== skill.content ||
		visibility !== skill.visibility ||
		JSON.stringify(files) !== JSON.stringify(skill.files);
	function apply(value: Skill) {
		setSkill(value);
		setContent(value.content);
		setFiles(value.files);
		setVisibility(value.visibility);
	}
	useEffect(() => {
		if (id)
			void api
				.get<Skill>(`/skills/${id}`)
				.then((r) => apply(r.data))
				.catch((e) => setError(getApiErrorMessage(e, "Could not load skill")));
	}, [id]);
	useEffect(() => {
		if (!dirty) return;
		const handler = (e: BeforeUnloadEvent) => {
			e.preventDefault();
		};
		window.addEventListener("beforeunload", handler);
		return () => window.removeEventListener("beforeunload", handler);
	}, [dirty]);
	async function save() {
		setBusy(true);
		setError("");
		setNotice("");
		try {
			const data = { content, files, visibility, revision: skill?.revision };
			const result = id
				? await api.put<Skill>(`/skills/${id}`, data)
				: await api.post<Skill>("/skills", data);
			apply(result.data);
			if (!id) router.replace(`/skills/${result.data.id}`);
			else
				setNotice(
					"Saved. Attached agents will use this content on their next run.",
				);
		} catch (e) {
			setError(getApiErrorMessage(e, "Could not save skill"));
		} finally {
			setBusy(false);
		}
	}
	async function upload(file: File) {
		if (file.size > 10 * 1024 * 1024) {
			setError("Files must be under 10 MB");
			return;
		}
		try {
			const bytes = new Uint8Array(await file.arrayBuffer());
			let value: SkillFile;
			try {
				value = {
					path: `scripts/${file.name}`,
					content: new TextDecoder("utf-8", { fatal: true }).decode(bytes),
					encoding: "utf-8",
				};
			} catch {
				let binary = "";
				for (const byte of bytes) binary += String.fromCharCode(byte);
				value = { path: file.name, content: btoa(binary), encoding: "base64" };
			}
			setFiles((current) => [...current, value]);
		} catch (e) {
			setError(getApiErrorMessage(e, "Could not read file"));
		}
	}
	async function download() {
		try {
			const r = await api.get(`/skills/${id}/export`, { responseType: "blob" });
			const url = URL.createObjectURL(r.data);
			const a = document.createElement("a");
			a.href = url;
			a.download = `${skill?.name ?? "skill"}.zip`;
			a.click();
			URL.revokeObjectURL(url);
		} catch (e) {
			setError(getApiErrorMessage(e, "Export failed"));
		}
	}
	async function remove() {
		if (!window.confirm("Delete this skill?")) return;
		setBusy(true);
		try {
			await api.delete(`/skills/${id}`);
			router.push("/skills");
		} catch (e) {
			setError(getApiErrorMessage(e, "Could not delete skill"));
			setBusy(false);
		}
	}
	return (
		<WorkspacePage
			slug="skills"
			title={skill?.name ?? "New skill"}
			intro="A SKILL.md file with YAML frontmatter and optional scripts. Save, then enable it in an agent’s settings."
			actions={
				<>
					<Link href="/skills" className="text-sm">
						All skills
					</Link>
					{id && (
						<WorkspaceTopBarButton
							onClick={() => void download()}
							disabled={busy || dirty}
						>
							Export
						</WorkspaceTopBarButton>
					)}
					{editable && (
						<WorkspaceTopBarButton
							onClick={() => void save()}
							disabled={busy || !dirty}
						>
							Save
						</WorkspaceTopBarButton>
					)}
				</>
			}
		>
			{error && (
				<p role="alert" className="mb-4 text-destructive">
					{error}
				</p>
			)}
			{notice && (
				<p role="status" className="mb-4 text-sm">
					{notice}
				</p>
			)}
			{id && !skill ? (
				<p>Loading skill…</p>
			) : (
				<div className="max-w-4xl space-y-6">
					<label className="block space-y-2">
						<span className="font-medium">SKILL.md</span>
						<textarea
							aria-label="SKILL.md"
							className={`${input} min-h-80 font-mono`}
							value={content}
							onChange={(e) => setContent(e.target.value)}
							disabled={!editable || busy}
							spellCheck={false}
						/>
					</label>
					<section className="space-y-4">
						<div className="flex items-center justify-between gap-3">
							<h2 className="font-medium">Scripts and files</h2>
							{editable && (
								<div className="flex gap-3 text-sm">
									<button
										type="button"
										disabled={busy}
										onClick={() =>
											setFiles((current) => [
												...current,
												{
													path: "scripts/script.py",
													content: "",
													encoding: "utf-8",
												},
											])
										}
									>
										Add script
									</button>
									<label className="cursor-pointer">
										Upload file
										<input
											type="file"
											className="sr-only"
											disabled={busy}
											onChange={(e) => {
												const f = e.target.files?.[0];
												if (f) void upload(f);
												e.target.value = "";
											}}
										/>
									</label>
								</div>
							)}
						</div>
						{!files.length && (
							<p className="text-sm text-muted-foreground">
								Optional. Add scripts or reference files used by this skill.
							</p>
						)}
						{files.map((file, i) => (
							<div key={i} className="space-y-3 rounded-lg border p-4">
								<div className="flex gap-3">
									<input
										aria-label={`File path ${i + 1}`}
										className={input}
										value={file.path}
										disabled={!editable || busy}
										onChange={(e) =>
											setFiles((current) =>
												current.map((f, j) =>
													j === i ? { ...f, path: e.target.value } : f,
												),
											)
										}
									/>
									{editable && (
										<button
											type="button"
											className="text-sm text-destructive"
											disabled={busy}
											onClick={() =>
												setFiles((current) => current.filter((_, j) => j !== i))
											}
										>
											Remove
										</button>
									)}
								</div>
								{file.encoding === "utf-8" ? (
									<textarea
										aria-label={`Contents of ${file.path}`}
										className={`${input} min-h-48 font-mono`}
										spellCheck={false}
										value={file.content}
										disabled={!editable || busy}
										onChange={(e) =>
											setFiles((current) =>
												current.map((f, j) =>
													j === i ? { ...f, content: e.target.value } : f,
												),
											)
										}
									/>
								) : (
									<p className="text-sm text-muted-foreground">Binary file</p>
								)}
							</div>
						))}
					</section>
					<label className="block max-w-sm space-y-2">
						<span className="text-sm">Sharing</span>
						<select
							className={input}
							value={visibility}
							disabled={!editable || busy}
							onChange={(e) =>
								setVisibility(e.target.value as "private" | "workspace")
							}
						>
							<option value="private">Private</option>
							<option value="workspace">Workspace</option>
						</select>
					</label>
					{id && editable && (
						<button
							type="button"
							className="text-sm text-destructive"
							disabled={busy}
							onClick={() => void remove()}
						>
							Delete skill
						</button>
					)}
				</div>
			)}
		</WorkspacePage>
	);
}
