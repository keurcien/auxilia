"use client";

import { useRouter } from "next/navigation";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import { useUserStore } from "@/stores/user-store";
import SkillEditor from "../components/skill-editor";

export default function NewSkillPage() {
	const router = useRouter();
	const user = useUserStore((state) => state.user);

	// The same guard the sources page uses, for the same reason: the library
	// buttons are already hidden, so anyone arriving here typed the URL and
	// would otherwise write a whole skill before the save returned a 403.
	if (user && user.role !== "admin" && user.role !== "editor") {
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
