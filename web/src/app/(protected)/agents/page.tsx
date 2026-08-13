"use client";

import { useState, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import AgentList from "@/app/(protected)/agents/components/agent-list";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import { UnderlineTabs } from "@/components/ui/underline-tabs";
import { ViewToggle, type ViewMode } from "@/components/ui/view-toggle";
import {
	WorkspacePage,
	WorkspaceTopBarButton,
} from "@/components/layout/workspace-page";
import { useUserStore } from "@/stores/user-store";
import { useQueryParamState } from "@/hooks/use-query-param-state";

const VIEW_MODE_STORAGE_KEY = "agents:view-mode";

// Persisted table/cards preference (table by default), exposed through
// useSyncExternalStore so the server render and hydration stay consistent
// without effect-driven state.
const viewModeListeners = new Set<() => void>();

function subscribeViewMode(listener: () => void) {
	viewModeListeners.add(listener);
	return () => {
		viewModeListeners.delete(listener);
	};
}

// In-session fallback when localStorage is unavailable (private mode).
let sessionViewMode: ViewMode = "table";

function readViewMode(): ViewMode {
	try {
		const stored = localStorage.getItem(VIEW_MODE_STORAGE_KEY);
		if (stored === "cards" || stored === "table") return stored;
	} catch {
		// Fall through to the in-session value.
	}
	return sessionViewMode;
}

function writeViewMode(mode: ViewMode) {
	sessionViewMode = mode;
	try {
		localStorage.setItem(VIEW_MODE_STORAGE_KEY, mode);
	} catch {
		// Persistence failed — the in-session fallback still applies.
	}
	viewModeListeners.forEach((listener) => {
		listener();
	});
}

export default function AgentsPage() {
	const router = useRouter();
	const user = useUserStore((state) => state.user);
	const [errorDialogOpen, setErrorDialogOpen] = useState(false);
	const [search, setSearch] = useQueryParamState("q");
	const [viewParam, setView] = useQueryParamState("view", "available");
	const view: "available" | "all" | "archived" =
		viewParam === "all" || viewParam === "archived" ? viewParam : "available";
	const viewMode = useSyncExternalStore(
		subscribeViewMode,
		readViewMode,
		() => "table" as ViewMode,
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
			fillHeight={viewMode === "table"}
			search={{
				placeholder: "Search agents…",
				value: search,
				onChange: setSearch,
			}}
			actions={
				<WorkspaceTopBarButton
					// Until /auth/me resolves the role check can't run — a click
					// would silently no-op, so keep the button disabled.
					disabled={!user}
					onClick={() => {
						handleCreateAgent();
					}}
				>
					<Plus className="size-3.5" />
					New agent
				</WorkspaceTopBarButton>
			}
			headerRight={
				<div className="flex items-center gap-3">
					<UnderlineTabs
						tabs={[
							{ key: "available", label: "Available to you" },
							{ key: "all", label: "All" },
							{ key: "archived", label: "Archived" },
						]}
						value={view}
						onChange={setView}
					/>
					<ViewToggle value={viewMode} onChange={writeViewMode} />
				</div>
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
				mode={viewMode}
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
