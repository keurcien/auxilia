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
	// Keyed by the id it was loaded for, rather than reset in an effect: a
	// late response for the previous skill can neither paint over this one nor
	// require a synchronous setState on navigation.
	const [loaded, setLoaded] = useState<{ id: string; skill: Skill } | null>(null);
	const [failed, setFailed] = useState<{ id: string; message: string } | null>(null);
	const skill = loaded?.id === id ? loaded.skill : null;
	const error = failed?.id === id ? failed.message : null;
	// `?edit=1` (the library's row menu) opens straight in edit mode; a
	// viewer who can't edit falls back to read mode below.
	const [editing, setEditing] = useState(searchParams.get("edit") === "1");
	const reviewOnOpen = searchParams.get("review") === "1";

	useEffect(() => {
		let current = true;
		getSkill(id)
			.then((next) => {
				if (current) setLoaded({ id, skill: next });
			})
			.catch((err: unknown) => {
				if (current) {
					setFailed({
						id,
						message: getApiErrorMessage(err, "This skill could not be loaded."),
					});
				}
			});
		return () => {
			current = false;
		};
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
				setLoaded({ id, skill: saved });
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
