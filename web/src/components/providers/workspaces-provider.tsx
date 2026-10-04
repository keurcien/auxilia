"use client";

import Image from "next/image";
import { useEffect, useState } from "react";

import { useAgentsStore } from "@/stores/agents-store";
import { useAppearanceStore } from "@/stores/appearance-store";
import { useMcpServersStore } from "@/stores/mcp-servers-store";
import { useSkillsStore } from "@/stores/skills-store";
import { useThreadsStore } from "@/stores/threads-store";
import { useTriggersStore } from "@/stores/triggers-store";
import { useWorkspacesStore } from "@/stores/workspaces-store";

let bootstrap: Promise<void> | null = null;

async function bootstrapProtectedApp(hydrate: () => Promise<void>): Promise<void> {
	await hydrate();
	if (!useWorkspacesStore.getState().isInitialized) return;

	await Promise.allSettled([
		useAgentsStore.getState().fetchAgents(),
		useThreadsStore.getState().fetchThreads(),
		useTriggersStore.getState().fetchTriggers(),
		useMcpServersStore.getState().fetchMcpServers(),
		useSkillsStore.getState().fetchSkills(),
		useAppearanceStore.getState().fetchAppearance(),
	]);
}

export function FullPageLoader() {
	return (
		<div
			role="status"
			aria-live="polite"
			aria-label="Loading workspace"
			className="fixed inset-0 z-[100] flex min-h-svh items-center justify-center bg-background"
		>
			<div className="flex flex-col items-center">
				<div className="relative grid size-14 place-items-center">
					<span className="absolute inset-1 rounded-full border border-border bg-card shadow-sm" />
					<span className="absolute inset-0 animate-spin rounded-full border-2 border-petrol/15 border-t-petrol motion-reduce:animate-none dark:border-white/10 dark:border-t-panel-terminal" />
					<Image
						src="/logo.svg"
						alt=""
						width={26}
						height={26}
						priority
						className="relative dark:invert"
					/>
				</div>
				<p className="mt-4 font-display text-[15px] font-semibold tracking-[-0.02em] text-foreground">
					auxilia
				</p>
				<p className="mt-1 text-[11px] font-medium text-meta dark:text-panel-dim">
					Loading workspace…
				</p>
			</div>
		</div>
	);
}

export function WorkspacesProvider({ children }: { children: React.ReactNode }) {
	const hydrate = useWorkspacesStore((state) => state.hydrate);
	const [isReady, setIsReady] = useState(false);

	useEffect(() => {
		let active = true;
		bootstrap ??= bootstrapProtectedApp(hydrate);
		void bootstrap
			.catch((error: unknown) => {
				console.error("Failed to bootstrap the protected app:", error);
			})
			.finally(() => {
				if (active) setIsReady(true);
			});
		return () => {
			active = false;
		};
	}, [hydrate]);

	if (!isReady) return <FullPageLoader />;
	return children;
}
