"use client";

import { useRouter } from "next/navigation";
import SkillEditor from "../components/skill-editor";

export default function NewSkillPage() {
	const router = useRouter();
	return (
		<SkillEditor
			onSaved={(skill) => {
				router.push(`/skills/${skill.id}`);
			}}
			onCancel={() => {
				router.push("/skills");
			}}
		/>
	);
}
