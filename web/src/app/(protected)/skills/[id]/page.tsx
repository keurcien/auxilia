"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Skill } from "@/types/skills";
import { useSkillsStore } from "@/stores/skills-store";
import { getApiErrorMessage } from "@/lib/api/errors";
import SkillEditor from "../components/skill-editor";

export default function SkillPage() {
	const params = useParams();
	const router = useRouter();
	const id = params.id as string;
	const getSkill = useSkillsStore((state) => state.getSkill);
	const [skill, setSkill] = useState<Skill | null>(null);
	const [error, setError] = useState<string | null>(null);
	// Read mode by default: most visits are to look a skill up, not edit it.
	const [editing, setEditing] = useState(false);

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
	return (
		<SkillEditor
			key={`${skill.id}:${skill.revision}:${editing ? "edit" : "read"}`}
			skill={skill}
			readOnly={!editing}
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
		/>
	);
}
