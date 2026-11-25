"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
	AddToAgentsDialog,
	type AttachedResource,
} from "@/components/editor/add-to-agents-dialog";
import AgentEditor from "../components/agent-editor";

export default function NewAgentPage() {
	const router = useRouter();
	const [created, setCreated] = useState<AttachedResource | null>(null);

	return (
		<>
			<AgentEditor
				onSaved={(agent) => {
					// An agent with subagents of its own cannot be used as one.
					if (agent.subagents.length > 0) {
						router.push(`/agents/${agent.id}`);
						return;
					}
					setCreated(agent);
				}}
				onCancel={() => {
					router.push("/agents");
				}}
			/>
			{created && (
				<AddToAgentsDialog
					key={created.id}
					kind="subagent"
					resource={created}
					onDone={() => {
						router.push(`/agents/${created.id}`);
					}}
				/>
			)}
		</>
	);
}
