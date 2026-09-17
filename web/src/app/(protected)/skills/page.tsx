"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import ConfirmDialog from "@/components/ui/confirm-dialog";
import { UnderlineTabs } from "@/components/ui/underline-tabs";
import { WorkspacePage, WorkspaceTopBarButton } from "@/components/layout/workspace-page";
import { useQueryParamState } from "@/hooks/use-query-param-state";
import { getApiErrorMessage } from "@/lib/api/errors";
import { useSkillsStore } from "@/stores/skills-store";
import { useUserStore } from "@/stores/user-store";
import { NewSkillChoices, NewSkillMenu } from "./components/new-skill-menu";
import SkillInUseDialog from "./components/skill-in-use-dialog";
import SkillSourceTable from "./components/skill-source-table";
import SkillTable from "./components/skill-table";
import { useDeleteSkill } from "./lib/use-delete-skill";

type View = "library" | "sources";

export default function SkillsPage() {
	const router = useRouter();
	const user = useUserStore((state) => state.user);
	const isAdmin = user?.role === "admin";
	const skills = useSkillsStore((state) => state.skills);
	const isInitialized = useSkillsStore((state) => state.isInitialized);
	const fetchSkills = useSkillsStore((state) => state.fetchSkills);
	const importSkill = useSkillsStore((state) => state.importSkill);
	const sources = useSkillsStore((state) => state.sources);
	const sourcesInitialized = useSkillsStore((state) => state.sourcesInitialized);
	const fetchSources = useSkillsStore((state) => state.fetchSources);
	const [search, setSearch] = useQueryParamState("q");
	const [viewParam, setViewParam] = useQueryParamState("view", "library");
	const view: View = viewParam === "sources" ? "sources" : "library";
	const [error, setError] = useState<string | null>(null);
	const [isImporting, setIsImporting] = useState(false);

	useEffect(() => {
		fetchSkills().catch((err: unknown) => {
			setError(getApiErrorMessage(err, "Failed to load the skills."));
		});
		fetchSources().catch((err: unknown) => {
			setError(getApiErrorMessage(err, "Failed to load the skill sources."));
		});
	}, [fetchSkills, fetchSources]);

	const visible = useMemo(() => {
		const term = search.trim().toLowerCase();
		if (!term) return skills;
		return skills.filter(
			(skill) =>
				skill.name.includes(term) || skill.description.toLowerCase().includes(term),
		);
	}, [skills, search]);

	const handleWrite = () => {
		router.push("/skills/new");
	};

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

	const remove = useDeleteSkill({
		onError: (err) => {
			setError(getApiErrorMessage(err, "Failed to delete the skill."));
		},
	});

	const isEmpty = isInitialized && skills.length === 0;
	const updates = skills.filter((skill) => skill.updateAvailable).length;

	return (
		<WorkspacePage
			slug="skills"
			title="Skills"
			intro={
				view === "sources"
					? "Repositories the workspace syncs skills from. Sync makes new versions available; each skill is adopted on its own, against a diff."
					: "Procedures any agent in the workspace can be given: a SKILL.md that says when to use it and what to do, plus optional scripts and references."
			}
			fillHeight
			search={
				view === "library"
					? { placeholder: "Search skills…", value: search, onChange: setSearch }
					: undefined
			}
			headerRight={
				<UnderlineTabs<View>
					tabs={[
						{ key: "library", label: "Library", count: isInitialized ? skills.length : undefined },
						{ key: "sources", label: "Sources", count: sourcesInitialized ? sources.length : undefined },
					]}
					value={view}
					onChange={(key) => {
						setViewParam(key);
					}}
					className="border-b border-border"
				/>
			}
			actions={
				view === "sources" ? (
					isAdmin ? (
						<WorkspaceTopBarButton
							onClick={() => {
								router.push("/skills/sources/new");
							}}
						>
							<Plus className="size-3.5" />
							Connect repository
						</WorkspaceTopBarButton>
					) : null
				) : (
					<NewSkillMenu
						disabled={isImporting}
						onWrite={handleWrite}
						onImport={(file) => {
							void handleImport(file);
						}}
					/>
				)
			}
		>
			<SkillInUseDialog
				open={remove.guard !== null}
				onOpenChange={(open) => {
					if (!open) remove.clearGuard();
				}}
				skillName={remove.guard?.skill.name ?? null}
				agents={remove.guard?.agents ?? []}
			/>
			<ConfirmDialog
				open={remove.pending !== null}
				onOpenChange={(open) => {
					if (!open) remove.clearPending();
				}}
				title="Delete this skill?"
				description={
					<>
						<span className="font-mono text-[12.5px] font-semibold text-petrol">
							{remove.pending?.name}
						</span>{" "}
						isn&apos;t enabled on any agent. Deleting it removes the SKILL.md and its
						files for everyone; threads that already used it are unaffected.
					</>
				}
				confirmLabel="Delete skill"
				destructive
				onConfirm={remove.confirmDelete}
				errorMessage="Could not delete the skill. Please try again."
			/>
			{error && (
				<div className="mb-3 shrink-0 rounded-[10px] bg-destructive/10 px-4 py-2.5 text-[13px] font-medium text-destructive">
					{error}
				</div>
			)}
			{isImporting && (
				<p className="mb-3 shrink-0 font-mono text-[11px] text-meta dark:text-panel-dim">
					importing…
				</p>
			)}
			{view === "sources" ? (
				sourcesInitialized && sources.length === 0 ? (
					<div className="rounded-[12px] border border-dashed border-input p-6 dark:border-white/10">
						<p className="font-mono text-[10.5px] font-semibold tracking-[0.09em] text-label dark:text-muted-foreground">
							NO REPOSITORY CONNECTED
						</p>
						<p className="mt-2 max-w-[560px] text-[13.5px] leading-[1.55] text-body dark:text-panel-body">
							Keep the company&apos;s skills in one git repository, reviewed and versioned there. Connect it and every
							<span className="font-mono text-[12px]"> skills/&lt;name&gt;/SKILL.md</span> becomes available in the
							library, pinned to its content; changes upstream are adopted per skill after a review.
						</p>
						{isAdmin ? (
							<button
								type="button"
								onClick={() => {
									router.push("/skills/sources/new");
								}}
								className="mt-5 inline-flex cursor-pointer items-center gap-1.5 rounded-[7px] bg-primary px-3.5 py-[7px] text-[12.5px] font-semibold text-primary-foreground transition-opacity hover:opacity-90"
							>
								<Plus className="size-3.5" />
								Connect repository
							</button>
						) : (
							<p className="mt-4 text-[12.5px] text-meta dark:text-panel-dim">A workspace admin can connect one.</p>
						)}
					</div>
				) : (
					<SkillSourceTable
						sources={sources}
						isLoading={!sourcesInitialized}
						canManage={isAdmin}
						onError={setError}
					/>
				)
			) : isEmpty ? (
				<div className="rounded-[12px] border border-dashed border-input p-6 dark:border-white/10">
					<p className="font-mono text-[10.5px] font-semibold tracking-[0.09em] text-label dark:text-muted-foreground">
						YOUR LIBRARY IS EMPTY
					</p>
					<p className="mt-2 max-w-[560px] text-[13.5px] leading-[1.55] text-body dark:text-panel-body">
						A skill is a folder with a SKILL.md — its name, when to use it, the steps —
						and optional files next to it. Every agent in the workspace can be given
						one; a skill with scripts needs an agent that runs code.
					</p>
					<div className="mt-5">
						<NewSkillChoices
							disabled={isImporting}
							onWrite={handleWrite}
							onImport={(file) => {
								void handleImport(file);
							}}
						/>
					</div>
				</div>
			) : (
				<>
					{updates > 0 && (
						<p className="mb-3 shrink-0 font-mono text-[11px] text-warning">
							{updates} skill{updates === 1 ? " has" : "s have"} a newer version in{" "}
							{updates === 1 ? "its" : "their"} repository — open {updates === 1 ? "it" : "them"} to review and adopt.
						</p>
					)}
				<SkillTable
					skills={visible}
					isLoading={!isInitialized}
					search={search}
					onClearSearch={() => {
						setSearch("");
					}}
					onDelete={(skill) => {
						setError(null);
						void remove.requestDelete(skill);
					}}
				/>
				</>
			)}
		</WorkspacePage>
	);
}
