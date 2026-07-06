"use client";

import { useRouter } from "next/navigation";
import TriggerEditor from "@/app/(protected)/triggers/components/trigger-editor";

export default function NewTriggerPage() {
	const router = useRouter();

	return (
		<div className="px-8 py-6">
			<TriggerEditor
				onSaved={(trigger) => {
					router.push(`/triggers/${trigger.id}`);
				}}
				onCancel={() => {
					router.push("/triggers");
				}}
			/>
		</div>
	);
}
