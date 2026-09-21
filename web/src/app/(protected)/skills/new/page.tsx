"use client";

import { useRouter } from "next/navigation";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import SkillEditor from "../components/skill-editor";
import { useRoleGate } from "../lib/use-role-gate";

export default function NewSkillPage() {
	const router = useRouter();
	const gate = useRoleGate("editor");

	// Nothing until the role is known: `/auth/me` in flight looks exactly like
	// "no user", so rendering the editor optimistically shows a member a whole
	// skill form that only 403s on save.
	if (gate === "pending") return null;

	if (gate === "denied") {
		return (
			<ForbiddenErrorDialog
				open
				onOpenChange={(open) => {
					if (!open) router.push("/skills");
				}}
				title="Insufficient privileges"
				message="Only an editor can add a skill to the library. Every skill already there is yours to use."
			/>
		);
	}

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
