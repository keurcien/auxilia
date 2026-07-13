"use client";

import { useRouter } from "next/navigation";
import AgentEditor from "../components/agent-editor";

export default function NewAgentPage() {
	const router = useRouter();

	return (
		<AgentEditor
			onSaved={(agent) => {
				router.push(`/agents/${agent.id}`);
			}}
			onCancel={() => {
				router.push("/agents");
			}}
		/>
	);
}
