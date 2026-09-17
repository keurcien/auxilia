"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { CircleAlert, CircleCheck, Eye, EyeOff, Loader2 } from "lucide-react";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import { HeaderButton, HeaderPrimaryButton, SubpageHeader } from "@/components/layout/subpage-header";
import { getApiErrorMessage } from "@/lib/api/errors";
import { useSkillsStore } from "@/stores/skills-store";
import { useUserStore } from "@/stores/user-store";
import { shortRevision, type SkillSourceCreate, type SkillSourceKind, type SkillSourcePreview } from "@/types/skills";
import { SkillRequirementChip } from "../../components/skill-requirement-chip";
import { SourceHostTile } from "../../components/source-host-tile";

const LABEL_CLASS = "text-[13px] font-semibold text-foreground";
const OPTIONAL_HINT = <span className="font-normal text-meta dark:text-panel-dim"> optional</span>;
const INPUT_CLASS =
	"w-full rounded-lg border border-input bg-card px-3 py-[9px] text-[13.5px] font-medium text-foreground outline-none transition-[border-color,box-shadow] placeholder:text-meta dark:placeholder:text-panel-dim focus:border-petrol focus:shadow-[0_0_0_3px_rgba(22,96,110,0.10)]";
const MONO_INPUT_CLASS = `${INPUT_CLASS} font-mono text-[12.5px] font-normal`;

const HOSTS: { value: SkillSourceKind; label: string; description: string }[] = [
	{ value: "github", label: "GitHub", description: "github.com or GitHub Enterprise. Read over the REST API." },
	{ value: "gitlab", label: "GitLab", description: "gitlab.com or any self-hosted instance. Read over API v4." },
];

/** github.com / gitlab.com are recognised; anything else needs a choice. */
function detectKind(url: string): SkillSourceKind | null {
	try {
		const host = new URL(url).hostname.toLowerCase();
		if (host === "github.com" || host === "www.github.com") return "github";
		if (host === "gitlab.com" || host === "www.gitlab.com") return "gitlab";
	} catch {
		// not a URL yet
	}
	return null;
}

function HostCards({ value, onChange, detected }: { value: SkillSourceKind; onChange: (v: SkillSourceKind) => void; detected: SkillSourceKind | null }) {
	return (
		<div role="radiogroup" aria-label="Host" className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
			{HOSTS.map((option) => {
				const selected = option.value === value;
				return (
					<button
						key={option.value}
						type="button"
						role="radio"
						aria-checked={selected}
						onClick={() => {
							onChange(option.value);
						}}
						className={`flex cursor-pointer flex-col gap-[5px] rounded-[10px] border p-[13px] text-left transition-[border-color,box-shadow] ${
							selected
								? "border-petrol bg-[#F7FAFA] shadow-[0_0_0_3px_rgba(22,96,110,0.08)] dark:bg-petrol/10"
								: "border-border hover:border-input"
						}`}
					>
						<span className="flex items-center gap-2">
							<span className={`flex size-3.5 shrink-0 items-center justify-center rounded-full border-[1.5px] ${selected ? "border-petrol" : "border-faint"}`}>
								{selected && <span className="size-[7px] rounded-full bg-petrol" />}
							</span>
							<span className="text-[13px] font-semibold text-foreground">{option.label}</span>
							{detected === option.value && (
								<span className="ml-auto font-mono text-[9.5px] text-meta dark:text-panel-dim">detected</span>
							)}
						</span>
						<span className={`text-[11.5px] leading-[1.45] ${selected ? "text-body dark:text-panel-body" : "text-subtle dark:text-muted-foreground"}`}>
							{option.description}
						</span>
					</button>
				);
			})}
		</div>
	);
}

/** The "test before adding" result: revision, then every skill with its chip and findings. */
function PreviewPanel({ preview }: { preview: SkillSourcePreview }) {
	const importable = preview.skills.filter((s) => s.ok).length;
	return (
		<div className="overflow-hidden rounded-[10px] border border-border bg-card">
			<div className="flex items-center gap-2.5 border-b border-hairline bg-sidebar px-4 py-2.5 dark:border-white/5 dark:bg-white/[0.02]">
				<CircleCheck className="size-4 shrink-0 text-success" />
				<span className="text-[13px] font-medium text-foreground">
					{importable} skill{importable === 1 ? "" : "s"} ready to import
				</span>
				<span className="ml-auto font-mono text-[11px] text-meta dark:text-panel-dim">@ {shortRevision(preview.revision)}</span>
			</div>
			{preview.skills.map((skill) => (
				<div key={skill.path} className="border-b border-hairline px-4 py-2.5 last:border-b-0 dark:border-white/5">
					<div className="flex min-w-0 items-center gap-2">
						<span className={`truncate font-mono text-[12.5px] font-semibold ${skill.ok ? "text-petrol" : "text-meta line-through"}`}>{skill.name}</span>
						<SkillRequirementChip scriptCount={skill.scriptCount} />
						<span className="ml-auto truncate font-mono text-[10.5px] text-meta dark:text-panel-dim">{skill.path}</span>
					</div>
					{skill.description && <p className="mt-0.5 truncate text-[12px] text-subtle dark:text-muted-foreground">{skill.description}</p>}
					{skill.issues.length > 0 && (
						<ul className="mt-1.5 flex flex-col gap-0.5">
							{skill.issues.map((issue, i) => (
								<li key={i} className={`font-mono text-[10.5px] ${issue.severity === "error" ? "text-[#B04A3A]" : "text-warning"}`}>
									{issue.code} {issue.message}
									{issue.suggestion ? ` → ${issue.suggestion}` : ""}
								</li>
							))}
						</ul>
					)}
				</div>
			))}
			{preview.issues.map((issue, i) => (
				<div key={`s-${i}`} className="border-t border-hairline px-4 py-2 font-mono text-[10.5px] text-warning dark:border-white/5">
					{issue.code} {issue.message}
				</div>
			))}
		</div>
	);
}

/**
 * Connect a repository as a skill source (design 15b: centred 640px form,
 * back link, header actions). Preview reads the repository without saving
 * anything; Connect saves it and runs the first sync.
 */
export default function NewSkillSourcePage() {
	const router = useRouter();
	const user = useUserStore((state) => state.user);
	const previewSource = useSkillsStore((state) => state.previewSource);
	const createSource = useSkillsStore((state) => state.createSource);
	const [url, setUrl] = useState("");
	const [kind, setKind] = useState<SkillSourceKind>("github");
	const [kindTouched, setKindTouched] = useState(false);
	const [ref, setRef] = useState("main");
	const [subpath, setSubpath] = useState("");
	const [token, setToken] = useState("");
	const [showToken, setShowToken] = useState(false);
	const [preview, setPreview] = useState<SkillSourcePreview | null>(null);
	const [busy, setBusy] = useState<"preview" | "create" | null>(null);
	const [error, setError] = useState<string | null>(null);

	const detected = useMemo(() => detectKind(url), [url]);
	const effectiveKind = kindTouched ? kind : (detected ?? kind);
	const urlValid = /^https:\/\/[^/\s]+\/[^/\s]+\/[^/\s]+/.test(url.trim());
	const payload = (): SkillSourceCreate => ({
		url: url.trim(),
		kind: effectiveKind,
		ref: ref.trim() || "main",
		subpath: subpath.trim() || null,
		token: token.trim() || null,
	});

	const handlePreview = async () => {
		setBusy("preview");
		setError(null);
		try {
			setPreview(await previewSource(payload()));
		} catch (err) {
			setPreview(null);
			setError(getApiErrorMessage(err, "Could not read the repository."));
		} finally {
			setBusy(null);
		}
	};

	const handleCreate = async () => {
		setBusy("create");
		setError(null);
		try {
			await createSource(payload());
			router.push("/skills?view=sources");
		} catch (err) {
			setError(getApiErrorMessage(err, "Could not connect the repository."));
		} finally {
			setBusy(null);
		}
	};

	if (user && user.role !== "admin") {
		return (
			<ForbiddenErrorDialog
				open
				onOpenChange={(open) => {
					if (!open) router.push("/skills");
				}}
				title="Insufficient privileges"
				message="Only a workspace admin can connect a skill repository."
			/>
		);
	}

	return (
		<div className="flex h-svh min-w-0 flex-1 flex-col bg-background">
			<SubpageHeader trail={[{ label: "workspace" }, { label: "skills", href: "/skills" }, { label: "connect repository" }]}>
				<HeaderButton
					disabled={busy !== null}
					onClick={() => {
						router.push("/skills?view=sources");
					}}
				>
					Cancel
				</HeaderButton>
				<HeaderPrimaryButton
					disabled={!urlValid || busy !== null}
					onClick={() => {
						void handleCreate();
					}}
				>
					{busy === "create" ? "Connecting…" : "Connect repository"}
				</HeaderPrimaryButton>
			</SubpageHeader>

			<div className="flex-1 overflow-y-auto px-4 py-8 sm:px-6 lg:px-8 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
				<div className="mx-auto max-w-[640px]">
					<Link href="/skills?view=sources" className="font-mono text-[11.5px] text-meta transition-colors hover:text-foreground dark:text-panel-dim">
						‹ Sources
					</Link>
					<div className="mt-4 flex items-start gap-4">
						<SourceHostTile url={url} kind={effectiveKind} size={38} />
						<div className="min-w-0">
							<h1 className="font-display text-[26px] font-bold tracking-[-0.035em] text-foreground">Connect a repository</h1>
							<p className="mt-1.5 text-[14px] leading-[1.55] text-body dark:text-panel-body">
								Every skill in the repository — a folder with a <span className="font-mono text-[12.5px]">SKILL.md</span> — becomes
								available in the library, pinned to its content. A change upstream is adopted per skill, against a diff; nothing
								here is edited from the app.
							</p>
						</div>
					</div>

					<div className="mt-8 flex flex-col gap-6">
						<div className="flex flex-col gap-1.5">
							<label htmlFor="source-url" className={LABEL_CLASS}>
								Repository address <span className="text-[#B04A3A]">*</span>
							</label>
							<input
								id="source-url"
								type="url"
								value={url}
								spellCheck={false}
								placeholder="https://github.com/acme/skills"
								onChange={(e) => {
									setUrl(e.target.value);
									setPreview(null);
								}}
								className={MONO_INPUT_CLASS}
							/>
							<p className="text-[12px] text-meta dark:text-panel-dim">Public or private. The layout follows the Agent Skills convention: <span className="font-mono">skills/&lt;name&gt;/SKILL.md</span>, categories one level deep, or a root <span className="font-mono">SKILL.md</span>.</p>
						</div>

						<div className="flex flex-col gap-2">
							<span className={LABEL_CLASS}>Host</span>
							<HostCards
								value={effectiveKind}
								detected={detected}
								onChange={(v) => {
									setKind(v);
									setKindTouched(true);
									setPreview(null);
								}}
							/>
						</div>

						<div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
							<div className="flex flex-col gap-1.5">
								<label htmlFor="source-ref" className={LABEL_CLASS}>
									Branch or tag
								</label>
								<input
									id="source-ref"
									type="text"
									value={ref}
									spellCheck={false}
									onChange={(e) => {
										setRef(e.target.value);
										setPreview(null);
									}}
									className={MONO_INPUT_CLASS}
								/>
								<p className="text-[12px] text-meta dark:text-panel-dim">Resolved to a commit at every sync. A tag pins the whole repository; a branch moves and skills are adopted one by one.</p>
							</div>
							<div className="flex flex-col gap-1.5">
								<label htmlFor="source-path" className={LABEL_CLASS}>
									Folder{OPTIONAL_HINT}
								</label>
								<input
									id="source-path"
									type="text"
									value={subpath}
									spellCheck={false}
									placeholder="skills/"
									onChange={(e) => {
										setSubpath(e.target.value);
										setPreview(null);
									}}
									className={MONO_INPUT_CLASS}
								/>
								<p className="text-[12px] text-meta dark:text-panel-dim">Only look under this folder of the repository.</p>
							</div>
						</div>

						<div className="flex flex-col gap-1.5">
							<label htmlFor="source-token" className={LABEL_CLASS}>
								Access token{OPTIONAL_HINT}
							</label>
							<div className="relative">
								<input
									id="source-token"
									type={showToken ? "text" : "password"}
									value={token}
									autoComplete="off"
									spellCheck={false}
									placeholder="Needed for a private repository"
									onChange={(e) => {
										setToken(e.target.value);
										setPreview(null);
									}}
									className={`${MONO_INPUT_CLASS} pr-10`}
								/>
								<button
									type="button"
									aria-label={showToken ? "Hide token" : "Show token"}
									onClick={() => {
										setShowToken((v) => !v);
									}}
									className="absolute right-2.5 top-1/2 -translate-y-1/2 cursor-pointer rounded p-1 text-meta transition-colors hover:text-foreground dark:text-panel-dim"
								>
									{showToken ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
								</button>
							</div>
							<p className="text-[12px] text-meta dark:text-panel-dim">
								A fine-grained token with read access to the repository&apos;s contents (GitHub) or a project token with{" "}
								<span className="font-mono">read_repository</span> (GitLab). Encrypted at rest, only ever sent to the host.
							</p>
						</div>

						<div className="flex items-center gap-3 rounded-[10px] border border-border bg-sidebar px-4 py-3 dark:bg-white/[0.02]">
							<span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-petrol-tint text-petrol dark:bg-white/10">
								{busy === "preview" ? <Loader2 className="size-4 animate-spin" /> : <CircleCheck className="size-4" />}
							</span>
							<div className="min-w-0 flex-1">
								<p className="text-[13px] font-semibold text-foreground">Preview before connecting</p>
								<p className="text-[12px] text-subtle dark:text-muted-foreground">Reads the repository once and lists what would be imported. Saves nothing.</p>
							</div>
							<HeaderButton
								accent
								className="px-3.5 py-[7px] text-[12.5px]"
								disabled={!urlValid || busy !== null}
								onClick={() => {
									void handlePreview();
								}}
							>
								Preview
							</HeaderButton>
						</div>

						{error && (
							<div className="flex items-center gap-2.5 rounded-[10px] bg-destructive/10 px-4 py-3 text-[13px] font-medium text-destructive">
								<CircleAlert className="size-4 shrink-0" />
								<span>{error}</span>
							</div>
						)}
						{preview && <PreviewPanel preview={preview} />}
					</div>
				</div>
			</div>
		</div>
	);
}
