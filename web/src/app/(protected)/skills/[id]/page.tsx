"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Skill } from "@/types/skills";
import { api } from "@/lib/api/client";
import { getApiErrorMessage } from "@/lib/api/errors";
import SkillEditor from "../skill-editor";

/**
 * The skill page: two-panel layout in read mode (markdown instructions,
 * disabled inputs) with an explicit Edit button that flips into the
 * editable draft. Save/Discard return to read mode.
 */
export default function SkillPage() {
	const { id } = useParams<{ id: string }>();
	const [skill, setSkill] = useState<Skill | null>(null);
	const [mode, setMode] = useState<"read" | "edit">("read");
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		let cancelled = false;
		api
			.get<Skill>(`/skills/${id}`)
			.then((response) => {
				if (!cancelled) setSkill(response.data);
			})
			.catch((err: unknown) => {
				if (!cancelled)
					setError(getApiErrorMessage(err, "Could not load skill."));
			});
		return () => {
			cancelled = true;
		};
	}, [id]);

	if (error) {
		return (
			<div className="flex h-svh flex-1 items-center justify-center bg-background">
				<p className="text-[13px] text-destructive">{error}</p>
			</div>
		);
	}
	if (!skill) {
		return (
			<div className="flex h-svh flex-1 items-center justify-center bg-background">
				<p className="font-mono text-[12px] text-meta dark:text-panel-dim">
					Loading skill…
				</p>
			</div>
		);
	}

	return (
		<SkillEditor
			// Keyed so entering edit mode snapshots the freshest skill and a
			// save never carries draft state over into read mode.
			key={`${skill.id}:${skill.revision}:${mode}`}
			skill={skill}
			readOnly={mode === "read"}
			onEdit={
				skill.canEdit
					? () => {
							setMode("edit");
						}
					: undefined
			}
			onSaved={(saved) => {
				setSkill(saved);
				setMode("read");
			}}
			onCancel={() => {
				setMode("read");
			}}
		/>
	);
}
