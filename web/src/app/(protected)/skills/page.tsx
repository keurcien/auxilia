"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Plus, Sparkles, Upload } from "lucide-react";
import {
	WorkspacePage,
	WorkspaceTopBarButton,
} from "@/components/layout/workspace-page";
import { HeaderButton } from "@/components/layout/subpage-header";
import { getApiErrorMessage } from "@/lib/api/errors";
import { useSkillsStore } from "@/stores/skills-store";
import { SkillSummary } from "@/types/skills";
import SkillCard from "./components/skill-card";

export default function SkillsPage() {
	const router = useRouter();
	const skills = useSkillsStore((state) => state.skills);
	const isInitialized = useSkillsStore((state) => state.isInitialized);
	const fetchSkills = useSkillsStore((state) => state.fetchSkills);
	const importSkill = useSkillsStore((state) => state.importSkill);
	const deleteSkill = useSkillsStore((state) => state.deleteSkill);
	const [search, setSearch] = useState("");
	const [error, setError] = useState<string | null>(null);
	const [isImporting, setIsImporting] = useState(false);
	const fileInput = useRef<HTMLInputElement>(null);

	useEffect(() => {
		fetchSkills().catch(() => {});
	}, [fetchSkills]);

	const term = search.trim().toLowerCase();
	const visible = term
		? skills.filter(
				(skill) =>
					skill.name.includes(term) ||
					skill.description.toLowerCase().includes(term),
			)
		: skills;

	const handleImport = async (file: File) => {
		setIsImporting(true);
		setError(null);
		try {
			const created = await importSkill(file);
			router.push(`/skills/${created.id}`);
		} catch (err) {
			setError(getApiErrorMessage(err, "Failed to import the skill."));
		} finally {
			setIsImporting(false);
		}
	};

	const handleDelete = (skill: SkillSummary) => {
		if (!confirm(`Delete the skill "${skill.name}"?`)) return;
		setError(null);
		deleteSkill(skill.id).catch((err: unknown) => {
			setError(getApiErrorMessage(err, "Failed to delete the skill."));
		});
	};

	return (
		<WorkspacePage
			slug="skills"
			title="Skills"
			intro="Reusable procedures — a SKILL.md with optional scripts and references — that any agent in the workspace can be given."
			search={{ placeholder: "Search skills…", value: search, onChange: setSearch }}
			actions={
				<>
					<input
						ref={fileInput}
						type="file"
						accept=".zip,.skill,.md"
						className="hidden"
						onChange={(e) => {
							const file = e.target.files?.[0];
							e.target.value = "";
							if (file) void handleImport(file);
						}}
					/>
					<HeaderButton
						disabled={isImporting}
						onClick={() => {
							fileInput.current?.click();
						}}
					>
						<Upload className="size-3.5" />
						{isImporting ? "Importing…" : "Import"}
					</HeaderButton>
					<WorkspaceTopBarButton
						onClick={() => {
							router.push("/skills/new");
						}}
					>
						<Plus className="size-3.5" />
						New skill
					</WorkspaceTopBarButton>
				</>
			}
		>
			{error && (
				<div className="mb-4 rounded-[10px] bg-destructive/10 px-4 py-3 text-[13.5px] font-medium text-destructive">
					{error}
				</div>
			)}
			{isInitialized && skills.length === 0 ? (
				<div className="flex flex-col items-center justify-center gap-4 rounded-2xl border border-dashed border-[#D7E0DB] dark:border-white/10 py-20">
					<div className="flex items-center justify-center size-12 rounded-2xl bg-[#EDF4F0] dark:bg-emerald-950/40">
						<Sparkles className="size-6 text-[#3D8B63] dark:text-emerald-400" />
					</div>
					<div className="text-center">
						<p className="font-[family-name:var(--font-jakarta-sans)] text-[16px] font-bold text-[#1E2D28] dark:text-foreground">
							No skills yet
						</p>
						<p className="mt-1 max-w-[380px] font-[family-name:var(--font-dm-sans)] text-[13.5px] text-[#6B7F76] dark:text-muted-foreground">
							Write one here, or import a folder exported from another Agent
							Skills tool.
						</p>
					</div>
					<button
						type="button"
						onClick={() => {
							router.push("/skills/new");
						}}
						className="inline-flex cursor-pointer items-center gap-1.5 rounded-[7px] bg-primary px-3.5 py-[7px] text-[12.5px] font-semibold text-primary-foreground transition-opacity hover:opacity-90"
					>
						<Plus className="size-4" />
						New skill
					</button>
				</div>
			) : visible.length === 0 && isInitialized ? (
				<div className="py-16 text-center font-[family-name:var(--font-dm-sans)] text-[13.5px] text-[#A3B5AD] dark:text-muted-foreground">
					No skill matches “{search}”.
				</div>
			) : (
				<div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
					{visible.map((skill) => (
						<SkillCard key={skill.id} skill={skill} onDelete={handleDelete} />
					))}
				</div>
			)}
		</WorkspacePage>
	);
}
