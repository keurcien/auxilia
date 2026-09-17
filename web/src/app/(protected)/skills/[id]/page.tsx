"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Skill } from "@/types/skills";
import { useSkillsStore } from "@/stores/skills-store";
import { getApiErrorMessage } from "@/lib/api/errors";
import SkillEditor from "../components/skill-editor";

export default function SkillPage() {
	const params = useParams();
	const router = useRouter();
	const searchParams = useSearchParams();
	const id = params.id as string;
	const getSkill = useSkillsStore((state) => state.getSkill);
	const [skill, setSkill] = useState<Skill | null>(null);
	const [error, setError] = useState<string | null>(null);
	// `?edit=1` (the library's row menu) opens straight in edit mode; a
	// viewer who can't edit falls back to read mode below.
	const [editing, setEditing] = useState(searchParams.get("edit") === "1");
	const reviewOnOpen = searchParams.get("review") === "1";

	useEffect(() => {
		getSkill(id)
			.then(setSkill)
			.catch((err: unknown) => {
				setError(getApiErrorMessage(err, "This skill could not be loaded."));
			});
	}, [getSkill, id]);

	if (error) {
		return (
			<div className="flex h-svh flex-1 items-center justify-center p-8 text-[13.5px] text-destructive">
				{error}
			</div>
		);
	}
	if (!skill) {
		return <div className="h-svh flex-1 bg-background" />;
	}
	const canEdit = skill.canEdit && editing;
	return (
		<SkillEditor
			key={`${skill.id}:${skill.revision}:${canEdit ? "edit" : "read"}`}
			skill={skill}
			readOnly={!canEdit}
			onEdit={
				skill.canEdit
					? () => {
							setEditing(true);
						}
					: undefined
			}
			onSaved={(saved) => {
				setSkill(saved);
				setEditing(false);
			}}
			onCancel={() => {
				setEditing(false);
			}}
			onDeleted={() => {
				router.push("/skills");
			}}
			reviewOnOpen={reviewOnOpen}
		/>
	);
}
