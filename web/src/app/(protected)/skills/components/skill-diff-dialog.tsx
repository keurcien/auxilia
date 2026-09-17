"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import {
	Dialog,
	DialogButton,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { getApiErrorMessage } from "@/lib/api/errors";
import { useSkillsStore } from "@/stores/skills-store";
import { shortRevision, type Skill, type SkillDiff } from "@/types/skills";

interface SkillDiffDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	skill: Skill;
	canAdopt: boolean;
	onAdopted: (skill: Skill) => void;
}

const CATEGORY_COPY: Record<string, { label: string; note: string; tone: "warn" | "trust" | "plain" }> = {
	description: { label: "Trigger", note: "the description changed — the skill may now fire on different requests", tone: "warn" },
	instructions: { label: "Instructions", note: "the SKILL.md body changed", tone: "plain" },
	scripts: { label: "Scripts", note: "executable content changed — review before adopting", tone: "trust" },
	requirements: { label: "Requirements", note: "what the scripts need from the environment changed", tone: "warn" },
	references: { label: "References", note: "reference files changed", tone: "plain" },
	assets: { label: "Assets", note: "asset files changed", tone: "plain" },
	other: { label: "Other", note: "metadata, license or other files changed", tone: "plain" },
};

function toneClass(tone: "warn" | "trust" | "plain"): string {
	switch (tone) {
		case "warn":
			return "bg-warning-bg text-warning";
		case "trust":
			return "bg-[#FBEFED] text-[#B04A3A] dark:bg-[#B04A3A]/15";
		case "plain":
			return "bg-neutral-bg text-subtle dark:bg-white/10 dark:text-panel-body";
	}
}

/** Unified diff lines coloured by prefix, mono on the hover surface. */
function Unified({ text }: { text: string }) {
	return (
		<pre className="max-h-[320px] w-full max-w-full overflow-auto whitespace-pre rounded-[6px] bg-hover p-3 font-mono text-[11px] leading-[1.55] text-foreground dark:bg-white/5 [scrollbar-width:thin]">
			{text.split("\n").map((line, i) => (
				<div
					key={i}
					className={
						line.startsWith("+") && !line.startsWith("+++")
							? "text-success"
							: line.startsWith("-") && !line.startsWith("---")
								? "text-[#B04A3A]"
								: line.startsWith("@@")
									? "text-petrol"
									: "text-subtle dark:text-muted-foreground"
					}
				>
					{line || " "}
				</div>
			))}
		</pre>
	);
}

/**
 * Review what the newest synced version of a sourced skill changes, and
 * adopt it. Categories first — the trigger changing is the highest-surprise
 * change and invisible in a text diff — then the per-file diffs.
 */
export default function SkillDiffDialog({ open, onOpenChange, skill, canAdopt, onAdopted }: SkillDiffDialogProps) {
	const getSkillDiff = useSkillsStore((state) => state.getSkillDiff);
	const adoptSkill = useSkillsStore((state) => state.adoptSkill);
	const [diff, setDiff] = useState<SkillDiff | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [adopting, setAdopting] = useState(false);

	useEffect(() => {
		if (!open) return;
		setDiff(null);
		setError(null);
		getSkillDiff(skill.id)
			.then(setDiff)
			.catch((err: unknown) => {
				setError(getApiErrorMessage(err, "Could not load the changes."));
			});
	}, [open, skill.id, skill.revision, getSkillDiff]);

	const handleAdopt = async () => {
		setAdopting(true);
		setError(null);
		try {
			onAdopted(await adoptSkill(skill.id));
			onOpenChange(false);
		} catch (err) {
			setError(getApiErrorMessage(err, "Could not adopt this version."));
		} finally {
			setAdopting(false);
		}
	};

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="max-h-[85vh] w-[calc(100vw-32px)] overflow-y-auto sm:max-w-[760px] [scrollbar-width:thin] [&>*]:min-w-0">
				<DialogHeader>
					<DialogTitle>Review changes</DialogTitle>
					<DialogDescription>
						<span className="font-mono text-[12.5px] font-semibold text-petrol">{skill.name}</span> from{" "}
						<span className="font-mono text-[12px]">{shortRevision(diff?.oldRevision ?? skill.sourceRevision)}</span> to{" "}
						<span className="font-mono text-[12px]">{shortRevision(diff?.newRevision ?? skill.available?.revision)}</span>
						{skill.sourceName ? ` in ${skill.sourceName}` : ""}. Agents keep running the current version until you adopt.
					</DialogDescription>
				</DialogHeader>

				{error && (
					<div className="rounded-[10px] bg-[#FBEFED] px-3.5 py-2.5 text-[13px] font-medium text-[#B04A3A] dark:bg-[#B04A3A]/10">{error}</div>
				)}
				{!diff && !error && (
					<div className="flex items-center gap-2 py-6 text-[13px] text-meta dark:text-panel-dim">
						<Loader2 className="size-4 animate-spin" /> Comparing versions…
					</div>
				)}
				{diff && diff.status === "unchanged" && (
					<p className="py-4 text-[13px] text-subtle dark:text-panel-body">Nothing to adopt — the library already holds the newest version.</p>
				)}
				{diff && diff.status === "changed" && (
					<div className="flex min-w-0 flex-col gap-4">
						<div className="flex flex-col gap-1.5">
							{diff.categories.map((category) => {
								const copy = CATEGORY_COPY[category] ?? { label: category, note: "", tone: "plain" as const };
								return (
									<div key={category} className="flex items-center gap-2.5">
										<span className={`inline-flex shrink-0 items-center rounded-[4px] px-2 py-[3px] font-mono text-[9.5px] font-semibold uppercase tracking-[0.05em] ${toneClass(copy.tone)}`}>
											{copy.label}
										</span>
										<span className="text-[12.5px] text-subtle dark:text-muted-foreground">{copy.note}</span>
									</div>
								);
							})}
						</div>
						<div className="flex min-w-0 flex-col gap-3">
							{diff.files.map((file) => (
								<div key={file.path} className="min-w-0 overflow-hidden rounded-[10px] border border-border">
									<div className="flex items-center gap-2.5 bg-sidebar px-3 py-2 dark:bg-white/[0.02]">
										<span className={`font-mono text-[9.5px] font-semibold uppercase ${file.status === "added" ? "text-success" : file.status === "removed" ? "text-[#B04A3A]" : "text-warning"}`}>
											{file.status}
										</span>
										<span className="truncate font-mono text-[12px] text-foreground">{file.path}</span>
										<span className="ml-auto font-mono text-[10.5px] text-meta dark:text-panel-dim">
											{file.binary ? `binary · ${file.oldSize ?? 0} → ${file.newSize ?? 0} B` : `${file.oldSize ?? 0} → ${file.newSize ?? 0} B`}
										</span>
									</div>
									{file.unified ? <div className="p-2"><Unified text={file.unified} /></div> : null}
								</div>
							))}
						</div>
					</div>
				)}

				<DialogFooter>
					<DialogButton
						variant="outline"
						onClick={() => {
							onOpenChange(false);
						}}
					>
						{canAdopt && diff?.status === "changed" ? "Not now" : "Close"}
					</DialogButton>
					{canAdopt && diff?.status === "changed" && (
						<DialogButton
							variant="primary"
							disabled={adopting}
							onClick={() => {
								void handleAdopt();
							}}
						>
							{adopting ? "Adopting…" : "Adopt this version"}
						</DialogButton>
					)}
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}
