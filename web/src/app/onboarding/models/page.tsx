"use client";

import WorkspaceModels from "@/app/(protected)/settings/workspace-models";
import { AuthShell } from "@/components/auth/auth-shell";

export default function ModelOnboardingPage() {
	const continueToAgents = () => {
		window.location.assign("/agents");
	};

	return (
		<AuthShell
			wide
			title="Connect an LLM"
			description="Add a provider API key, then choose which models your workspace can use. Keys are encrypted before they are stored."
			footer={
				<>
					You can add or replace keys later in{" "}
					<span className="font-semibold text-petrol">Settings → Models</span>
				</>
			}
		>
			<WorkspaceModels
				syncOnMount
				showSyncControl={false}
				onForbidden={continueToAgents}
			/>

			<button
				type="button"
				onClick={continueToAgents}
				className="mt-1.5 cursor-pointer rounded-md bg-ink p-3.5 text-[15px] font-semibold text-white transition-opacity hover:opacity-90"
			>
				Continue to agents →
			</button>
		</AuthShell>
	);
}
