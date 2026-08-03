"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import AgentList from "@/app/(protected)/agents/components/agent-list";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import { UnderlineTabs } from "@/components/ui/underline-tabs";
import {
	WorkspacePage,
	WorkspaceTopBarButton,
} from "@/components/layout/workspace-page";
import { useUserStore } from "@/stores/user-store";

export default function AgentsPage() {
	const router = useRouter();
	const user = useUserStore((state) => state.user);
	const [errorDialogOpen, setErrorDialogOpen] = useState(false);
	const [search, setSearch] = useState("");
	const [view, setView] = useState<"available" | "all" | "archived">(
		"available",
	);

	const handleCreateAgent = () => {
		if (!user) return;
		if (user.role === "member") {
			setErrorDialogOpen(true);
			return;
		}
		router.push("/agents/new");
	};

	return (
		<WorkspacePage
			slug="agents"
			title="Agents"
			intro="Assistants connected to your team's tools. Chat with them, or let triggers run them on a schedule."
			search={{
				placeholder: "Search agents…",
				value: search,
				onChange: setSearch,
			}}
			actions={
				<WorkspaceTopBarButton
					onClick={() => {
						handleCreateAgent();
					}}
				>
					<Plus className="size-3.5" />
					New agent
				</WorkspaceTopBarButton>
			}
			headerRight={
				<UnderlineTabs
					tabs={[
						{ key: "available", label: "Available to you" },
						{ key: "all", label: "All" },
						{ key: "archived", label: "Archived" },
					]}
					value={view}
					onChange={setView}
				/>
			}
		>
			<ForbiddenErrorDialog
				open={errorDialogOpen}
				onOpenChange={setErrorDialogOpen}
				title="Insufficient privileges"
				message="You need at least editor permissions to create agents."
			/>
			<AgentList
				key={view === "archived" ? "archived" : "active"}
				view={view}
				search={search}
				onClearSearch={() => {
					setSearch("");
				}}
				onCreateAgent={() => {
					handleCreateAgent();
				}}
			/>
		</WorkspacePage>
	);
}
