"use client";
import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api/client";
import { getApiErrorMessage } from "@/lib/api/errors";
import { Skill, SkillBundle } from "@/types/skills";
import { Thread } from "@/types/threads";
import { Agent } from "@/types/agents";
import { useAgentsStore } from "@/stores/agents-store";
import { useModelsStore } from "@/stores/models-store";
import { useThreadsStore } from "@/stores/threads-store";
import { usePendingMessageStore } from "@/stores/pending-message-store";
import { getDefaultModel } from "@/lib/utils/get-default-model";
import {
	WorkspacePage,
	WorkspaceTopBarButton,
} from "@/components/layout/workspace-page";
import { AgentPicker } from "@/components/editor/agent-picker";
import { ModelPickerChip } from "@/components/editor/model-picker-chip";

const empty: SkillBundle = {
	name: "",
	title: "",
	description: "",
	instructions: "",
	requiresCode: false,
	requiredMcpServerIds: [],
	files: [],
	examples: [],
	changeSummary: "",
};
const input = "w-full rounded-lg border bg-background px-3 py-2 text-sm";
interface TestRecord {
	id: string;
	threadId: string;
	result: string | null;
	notes: string;
	createdAt: string;
}
export default function SkillEditor({ id }: { id?: string }) {
	const router = useRouter();
	const [skill, setSkill] = useState<Skill>();
	const [bundle, setBundle] = useState<SkillBundle>(empty);
	const [visibility, setVisibility] = useState<"private" | "workspace">(
		"private",
	);
	const [tab, setTab] = useState("Instructions");
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState("");
	const [notice, setNotice] = useState("");
	const [agentId, setAgentId] = useState<string | null>(null);
	const [chosenModel, setModelId] = useState<string | null>(null);
	const [prompt, setPrompt] = useState("");
	const [tests, setTests] = useState<TestRecord[]>([]);
	const [servers, setServers] = useState<{ id: string; name: string }[]>([]);
	const agents = useAgentsStore((s) => s.agents);
	const models = useModelsStore((s) => s.models);
	const modelId = chosenModel ?? getDefaultModel(models) ?? null;
	const fetchModels = useModelsStore((s) => s.fetchModels);
	const addThread = useThreadsStore((s) => s.addThread);
	const pending = usePendingMessageStore((s) => s.setPendingMessage);
	const editable = !id || skill?.canEdit;
	const dirty = skill
		? JSON.stringify(bundle) !== JSON.stringify(skill.draft) ||
			visibility !== skill.visibility
		: true;
	const load = useCallback(async () => {
		if (!id) return;
		const r = await api.get<Skill>(`/skills/${id}`);
		setSkill(r.data);
		setBundle(r.data.draft);
		setVisibility(r.data.visibility);
		if (r.data.canEdit) {
			const t = await api.get<TestRecord[]>(`/skills/${id}/tests`);
			setTests(t.data);
		}
	}, [id]);
	useEffect(() => {
		void Promise.resolve()
			.then(load)
			.catch((e) => {
				setError(getApiErrorMessage(e, "Could not load skill"));
			});
		void fetchModels();
		void api
			.get<
				| { items?: { id: string; name: string }[] }
				| { id: string; name: string }[]
			>("/mcp-servers")
			.then((r) => {
				setServers(Array.isArray(r.data) ? r.data : (r.data.items ?? []));
			})
			.catch(() => {});
	}, [load, fetchModels]);

	useEffect(() => {
		if (!dirty) return;
		const handler = (e: BeforeUnloadEvent) => {
			e.preventDefault();
		};
		window.addEventListener("beforeunload", handler);
		return () => {
			window.removeEventListener("beforeunload", handler);
		};
	}, [dirty]);
	function field<K extends keyof SkillBundle>(key: K, value: SkillBundle[K]) {
		setBundle((b) => ({ ...b, [key]: value }));
	}
	async function action(fn: () => Promise<void>) {
		setBusy(true);
		setError("");
		setNotice("");
		try {
			await fn();
		} catch (e) {
			setError(getApiErrorMessage(e, "Action failed"));
		} finally {
			setBusy(false);
		}
	}
	async function save() {
		const payload = { bundle, visibility, revision: skill?.revision };
		const r = id
			? await api.put<Skill>(`/skills/${id}`, payload)
			: await api.post<Skill>("/skills", payload);
		setSkill(r.data);
		setBundle(r.data.draft);
		setNotice("Draft saved");
		if (!id) router.replace(`/skills/${r.data.id}`);
		return r.data;
	}
	async function openChat(text: string, test = false) {
		if (!agentId || !modelId)
			throw new Error("Choose an agent and model first");
		let thread: Thread;
		let message = text;
		if (test && id) {
			const r = await api.post<{ thread: Thread; prompt: string }>(
				`/skills/${id}/tests`,
				{ agentId, modelId, prompt: text },
			);
			thread = r.data.thread;
			message = r.data.prompt;
		} else {
			const r = await api.post<Thread>("/threads", {
				agentId,
				modelId,
				firstMessageContent: text,
			});
			thread = r.data;
		}
		pending(thread.id, { text: message, files: [] });
		addThread(thread);
		router.push(`/agents/${agentId}/chat/${thread.id}`);
	}
	async function addFiles(files: FileList | null) {
		if (!files) return;
		const added = await Promise.all(
			Array.from(files).map(async (file) => {
				if (file.size > 10 * 1024 * 1024) throw new Error("File exceeds 10 MB");
				const bytes = new Uint8Array(await file.arrayBuffer());
				let content: string;
				let encoding: "utf-8" | "base64" = "utf-8";
				try {
					content = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
				} catch {
					let binary = "";
					for (const byte of bytes) binary += String.fromCharCode(byte);
					content = btoa(binary);
					encoding = "base64";
				}
				return { path: `assets/${file.name}`, content, encoding };
			}),
		);
		field("files", [...bundle.files, ...added]);
	}
	if (id && !skill)
		return <div className="p-8">{error || "Loading skill…"}</div>;
	return (
		<WorkspacePage
			slug="skills"
			title={bundle.title || "New skill"}
			intro="Describe when to use this procedure. Save a draft, try an example, then publish a version for your agents."
			actions={
				<>
					<Link href="/skills" className="text-sm">
						All skills
					</Link>
					{editable && (
						<WorkspaceTopBarButton
							disabled={busy || !dirty}
							onClick={() => {
								void action(async () => {
									await save();
								});
							}}
						>
							Save draft
						</WorkspaceTopBarButton>
					)}
					{id && editable && (
						<WorkspaceTopBarButton
							disabled={busy || dirty}
							onClick={() => {
								void action(async () => {
									const r = await api.post<Skill>(`/skills/${id}/publish`, {
										revision: skill?.revision,
									});
									setSkill(r.data);
									setNotice(
										"Published. Choose the new version on each agent to apply it.",
									);
								});
							}}
						>
							Publish version
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
				<p role="status" className="mb-4 text-primary">
					{notice}
				</p>
			)}
			<div className="mb-5 flex flex-wrap gap-2">
				{["Instructions", "Files", "Try & teach", "History", "Agents"].map(
					(t) => (
						<button
							key={t}
							onClick={() => {
								setTab(t);
							}}
							className={`rounded-lg px-4 py-2 text-sm ${tab === t ? "bg-primary text-primary-foreground" : "bg-muted"}`}
						>
							{t}
						</button>
					),
				)}
				{dirty && (
					<span className="p-2 text-sm text-muted-foreground">
						Unsaved draft
					</span>
				)}
			</div>
			{tab === "Instructions" && (
				<fieldset disabled={!editable || busy} className="grid max-w-4xl gap-5">
					<label className="space-y-2">
						Name
						<input
							className={input}
							value={bundle.title}
							onChange={(e) => {
								field("title", e.target.value);
								if (!skill)
									field(
										"name",
										e.target.value
											.toLowerCase()
											.replace(/[^a-z0-9]+/g, "-")
											.replace(/^-|-$/g, ""),
									);
							}}
						/>
					</label>
					<label className="space-y-2">
						Identifier
						<input
							className={input}
							disabled={!!skill?.versions.length}
							value={bundle.name}
							onChange={(e) => {
								field("name", e.target.value);
							}}
						/>
					</label>
					<label className="space-y-2">
						When should the agent use this?
						<textarea
							className={input}
							rows={2}
							value={bundle.description}
							onChange={(e) => {
								field("description", e.target.value);
							}}
							placeholder="Use when preparing a monthly account review…"
						/>
					</label>
					<label className="space-y-2">
						Procedure
						<textarea
							className={`${input} font-mono`}
							rows={16}
							value={bundle.instructions}
							onChange={(e) => {
								field("instructions", e.target.value);
							}}
							placeholder="Explain the inputs, steps, expected output, and exceptions…"
						/>
					</label>
					<label className="flex gap-2">
						<input
							type="checkbox"
							checked={bundle.requiresCode}
							onChange={(e) => {
								field("requiresCode", e.target.checked);
							}}
						/>
						Requires code execution
					</label>
					<div>
						<p className="mb-2">Required MCP connections</p>
						{servers.map((s) => (
							<label key={s.id} className="mr-4 inline-flex gap-2">
								<input
									type="checkbox"
									checked={bundle.requiredMcpServerIds.includes(s.id)}
									onChange={(e) => {
										field(
											"requiredMcpServerIds",
											e.target.checked
												? [...bundle.requiredMcpServerIds, s.id]
												: bundle.requiredMcpServerIds.filter((x) => x !== s.id),
										);
									}}
								/>
								{s.name}
							</label>
						))}
					</div>
					<label>
						Sharing
						<select
							className={input}
							value={visibility}
							onChange={(e) => {
								setVisibility(e.target.value as "private" | "workspace");
							}}
						>
							<option value="private">Private</option>
							<option value="workspace">
								Workspace — everyone can read and use
							</option>
						</select>
					</label>
					<label>
						Change summary
						<input
							className={input}
							value={bundle.changeSummary}
							onChange={(e) => {
								field("changeSummary", e.target.value);
							}}
						/>
					</label>
				</fieldset>
			)}
			{tab === "Files" && (
				<div className="max-w-4xl space-y-4">
					<p className="text-sm text-muted-foreground">
						Use relative paths such as scripts/reconcile.py. Refer to them in
						the procedure. Maximum bundle size: 10 MB.
					</p>
					{editable && (
						<div className="flex gap-4">
							<button
								className="rounded border px-3 py-2"
								onClick={() => {
									field("files", [
										...bundle.files,
										{
											path: `scripts/script-${bundle.files.length + 1}.py`,
											content: "",
											encoding: "utf-8",
										},
									]);
									field("requiresCode", true);
								}}
							>
								Add script
							</button>
							<label className="cursor-pointer rounded border px-3 py-2">
								Upload files
								<input
									className="sr-only"
									type="file"
									multiple
									onChange={(e) => {
										void action(() => addFiles(e.target.files));
									}}
								/>
							</label>
						</div>
					)}
					{bundle.files.map((f, i) => (
						<div key={i} className="space-y-2 rounded-xl border p-4">
							<div className="flex gap-3">
								<input
									aria-label="File path"
									className={input}
									disabled={!editable}
									value={f.path}
									onChange={(e) => {
										field(
											"files",
											bundle.files.map((v, n) =>
												n === i ? { ...v, path: e.target.value } : v,
											),
										);
									}}
								/>
								{editable && (
									<button
										onClick={() => {
											field(
												"files",
												bundle.files.filter((_, n) => n !== i),
											);
										}}
									>
										Remove
									</button>
								)}
							</div>
							{f.encoding === "utf-8" ? (
								<textarea
									aria-label={`Contents of ${f.path}`}
									className={`${input} font-mono`}
									rows={10}
									disabled={!editable}
									value={f.content}
									onChange={(e) => {
										field(
											"files",
											bundle.files.map((v, n) =>
												n === i ? { ...v, content: e.target.value } : v,
											),
										);
									}}
								/>
							) : (
								<p className="text-sm text-muted-foreground">
									Binary asset included in the bundle
								</p>
							)}
						</div>
					))}
				</div>
			)}
			{tab === "Try & teach" && (
				<div className="max-w-3xl space-y-5">
					<p>
						Tests use a saved copy of this draft in a new conversation.
						Connected tools can perform real actions under the agent’s existing
						approval rules.
					</p>
					<AgentPicker value={agentId} onChange={setAgentId} />
					<ModelPickerChip value={modelId} onChange={setModelId} />
					<textarea
						className={input}
						rows={4}
						value={prompt}
						onChange={(e) => {
							setPrompt(e.target.value);
						}}
						placeholder="Enter an example task, or describe the improvement you want…"
					/>
					<div className="flex gap-3">
						<WorkspaceTopBarButton
							disabled={
								!id || busy || dirty || !agentId || !modelId || !prompt.trim()
							}
							onClick={() => {
								void action(() => openChat(prompt, true));
							}}
						>
							Try saved draft
						</WorkspaceTopBarButton>
						<button
							disabled={busy || !agentId || !modelId || !prompt.trim() || dirty}
							onClick={() => {
								void action(() =>
									openChat(
										`Help me ${id ? `improve skill ${id}. Read its draft first and preserve existing files unless I ask to change them.` : "create a reusable skill."} ${prompt}\nSave the result as a draft using save_skill_draft. Do not publish it.`,
									),
								);
							}}
						>
							Edit with AI
						</button>
					</div>
					<p className="text-sm text-muted-foreground">
						In an existing conversation, ask “Save this as a skill” to capture a
						successful routine.
					</p>
					<h3 className="font-semibold">Saved examples</h3>
					{bundle.examples.map((e, i) => (
						<div key={i} className="space-y-2 rounded border p-3">
							<input
								aria-label="Example prompt"
								className={input}
								disabled={!editable}
								value={e.prompt}
								onChange={(event) => {
									field(
										"examples",
										bundle.examples.map((v, n) =>
											n === i ? { ...v, prompt: event.target.value } : v,
										),
									);
								}}
							/>
							<textarea
								aria-label="Expected result"
								className={input}
								disabled={!editable}
								placeholder="Expected result"
								value={e.expected}
								onChange={(event) => {
									field(
										"examples",
										bundle.examples.map((v, n) =>
											n === i ? { ...v, expected: event.target.value } : v,
										),
									);
								}}
							/>
							<button
								onClick={() => {
									setPrompt(e.prompt);
								}}
							>
								Use example
							</button>
							{editable && (
								<button
									className="ml-4"
									onClick={() => {
										field(
											"examples",
											bundle.examples.filter((_, n) => n !== i),
										);
									}}
								>
									Remove
								</button>
							)}
						</div>
					))}
					{editable && (
						<button
							onClick={() => {
								field("examples", [
									...bundle.examples,
									{ prompt: prompt || "Example task", expected: "" },
								]);
							}}
						>
							Add example
						</button>
					)}
					<h3 className="font-semibold">Test history</h3>
					{tests.map((t) => (
						<div
							className="flex flex-wrap items-center gap-3 rounded border p-3"
							key={t.id}
						>
							<span>{new Date(t.createdAt).toLocaleString()}</span>
							<span>{t.result || "Not reviewed"}</span>
							<button
								onClick={() => {
									void action(async () => {
										const r = await api.get<Thread>(`/threads/${t.threadId}`);
										router.push(`/agents/${r.data.agentId}/chat/${t.threadId}`);
									});
								}}
							>
								Open conversation
							</button>
							{editable &&
								["passed", "failed"].map((result) => (
									<button
										key={result}
										onClick={() => {
											void action(async () => {
												await api.put(`/skills/${id}/tests/${t.threadId}`, {
													result,
													notes: "",
												});
												await load();
											});
										}}
									>
										Mark {result}
									</button>
								))}
						</div>
					))}
				</div>
			)}
			{tab === "History" && (
				<div className="space-y-4">
					<p className="text-sm text-muted-foreground">
						Restoring copies a published version into the draft. It does not
						change agents until you publish and select a version.
					</p>
					{skill?.versions.map((v) => (
						<div key={v.id} className="rounded-xl border p-4">
							<div className="flex flex-wrap gap-4">
								<strong>Version {v.number}</strong>
								<span>{new Date(v.createdAt).toLocaleString()}</span>
								<span>{v.bundle.changeSummary || "Published version"}</span>
								{editable && (
									<button
										disabled={busy || dirty}
										onClick={() => {
											void action(async () => {
												const r = await api.post<Skill>(
													`/skills/${id}/restore/${v.id}`,
													{ revision: skill.revision },
												);
												setSkill(r.data);
												setBundle(r.data.draft);
												setNotice("Restored to draft");
											});
										}}
									>
										Restore to draft
									</button>
								)}
								<button
									onClick={() => {
										void action(async () => {
											const r = await api.get<Blob>(`/skills/${id}/export`, {
												params: { versionId: v.id },
												responseType: "blob",
											});
											const url = URL.createObjectURL(r.data);
											const a = document.createElement("a");
											a.href = url;
											a.download = `${bundle.name}-v${v.number}.zip`;
											a.click();
											URL.revokeObjectURL(url);
										});
									}}
								>
									Export bundle
								</button>
							</div>
							<details className="mt-3">
								<summary>View instructions</summary>
								<pre className="mt-2 whitespace-pre-wrap text-sm">
									{v.bundle.instructions}
								</pre>
							</details>
						</div>
					))}
					{!skill?.versions.length && (
						<p>No published versions yet. Save and publish when ready.</p>
					)}
					{id && editable && (
						<button
							className="text-destructive"
							onClick={() => {
								if (confirm("Delete this skill and its history?"))
									void action(async () => {
										await api.delete(`/skills/${id}`);
										router.push("/skills");
									});
							}}
						>
							Delete skill
						</button>
					)}
				</div>
			)}
			{tab === "Agents" && (
				<div className="max-w-3xl space-y-4">
					<p>
						Choose a published version for each agent. Updating a skill never
						silently changes its agents.
					</p>
					{!skill?.versions.length && <p>Publish a version first.</p>}
					{agents
						.filter((a: Agent) =>
							["owner", "admin", "editor"].includes(
								a.currentUserPermission ?? "",
							),
						)
						.map((a) => (
							<div
								className="flex items-center justify-between gap-4 rounded border p-4"
								key={a.id}
							>
								<Link href={`/agents/${a.id}`}>{a.name}</Link>
								<select
									aria-label={`Version for ${a.name}`}
									className="rounded border bg-background p-2"
									defaultValue=""
									disabled={busy || !skill?.versions.length}
									onChange={(e) => {
										const versionId = e.target.value;
										if (versionId)
											void action(async () => {
												await api.put(`/agents/${a.id}/skills/${id}`, {
													versionId,
												});
												setNotice(`Applied to ${a.name}`);
											});
									}}
								>
									<option value="">Apply a version…</option>
									{skill?.versions.map((v) => (
										<option key={v.id} value={v.id}>
											Version {v.number}
										</option>
									))}
								</select>
							</div>
						))}
				</div>
			)}
		</WorkspacePage>
	);
}
