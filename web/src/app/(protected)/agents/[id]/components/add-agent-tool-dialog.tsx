"use client";

import { useState, useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";
import Image from "next/image";
import { Plus } from "lucide-react";
import { api } from "@/lib/api/client";
import { MCPServer } from "@/types/mcp-servers";
import { Sandbox } from "@/types/sandboxes";
import {
	SANDBOX_PROVIDER_ICONS,
	SANDBOX_PROVIDER_LABELS,
} from "@/lib/sandbox-providers";
import {
	Dialog,
	DialogButton,
	DialogContent,
	DialogDescription,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { shouldCloseAddToolDialogAfterServerAdded } from "../lib/mcp-server-assignment";

interface AddAgentToolDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	/** Servers already attached in the draft. */
	attachedServerIds: string[];
	/** Sandboxes already attached in the draft (at most one). */
	attachedSandboxIds: string[];
	/** Draft update: attach a server (tools stay null until synced/edited). */
	onAddServer: (serverId: string) => void;
	/** Draft update: attach a sandbox (replaces the current one, if any). */
	onAddSandbox: (sandboxId: string) => void;
}

interface AvailableMCPServerCardProps {
	server: MCPServer;
	onAdd: (serverId: string) => void;
}

function AvailableMCPServerCard({ server, onAdd }: AvailableMCPServerCardProps) {
	return (
		<div className="flex items-center gap-3 rounded-[10px] border border-hairline bg-canvas px-4 py-3 transition-colors hover:bg-sidebar dark:bg-white/5 dark:hover:bg-white/10">
			<Image
				unoptimized
				src={
					server.iconUrl ??
					"https://pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev/assets/icons/mcp.png"
				}
				alt={server.name}
				width={24}
				height={24}
				className="shrink-0 rounded-md"
			/>
			<div className="min-w-0 flex-1">
				<h3 className="truncate text-[13.5px] font-semibold text-ink dark:text-panel-button">
					{server.name}
				</h3>
			</div>
			<button
				className="flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-[7px] border border-input text-label outline-none transition-colors hover:border-border-hover hover:text-ink focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 dark:border-white/10 dark:hover:bg-white/10 dark:hover:text-panel-button"
				onClick={() => {
					onAdd(server.id);
				}}
				aria-label={`Add ${server.name}`}
			>
				<Plus className="size-3.5" />
			</button>
		</div>
	);
}

function AvailableSandboxCard({
	sandbox,
	onAdd,
}: {
	sandbox: Sandbox;
	onAdd: (sandboxId: string) => void;
}) {
	return (
		<div className="flex items-center gap-3 rounded-[10px] border border-hairline bg-canvas px-4 py-3 transition-colors hover:bg-sidebar dark:bg-white/5 dark:hover:bg-white/10">
			<Image
				unoptimized
				src={SANDBOX_PROVIDER_ICONS[sandbox.provider]}
				alt={SANDBOX_PROVIDER_LABELS[sandbox.provider]}
				width={24}
				height={24}
				className="shrink-0 rounded-md"
			/>
			<div className="min-w-0 flex-1">
				<h3 className="truncate text-[13.5px] font-semibold text-ink dark:text-panel-button">
					{sandbox.name}
				</h3>
				<span className="font-mono text-[9.5px] font-semibold tracking-[0.06em] text-meta uppercase dark:text-panel-dim">
					{SANDBOX_PROVIDER_LABELS[sandbox.provider]}
				</span>
			</div>
			<button
				className="flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-[7px] border border-input text-label outline-none transition-colors hover:border-border-hover hover:text-ink focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 dark:border-white/10 dark:hover:bg-white/10 dark:hover:text-panel-button"
				onClick={() => {
					onAdd(sandbox.id);
				}}
				aria-label={`Add ${sandbox.name}`}
			>
				<Plus className="size-3.5" />
			</button>
		</div>
	);
}

function SandboxSection({
	attachedSandboxIds,
	onOpenChange,
	onAddSandbox,
}: {
	attachedSandboxIds: string[];
	onOpenChange: (open: boolean) => void;
	onAddSandbox: (sandboxId: string) => void;
}) {
	const [allSandboxes, setAllSandboxes] = useState<Sandbox[]>([]);

	useEffect(() => {
		api.get("/sandboxes").then((res) => {
			setAllSandboxes(res.data as Sandbox[]);
		});
	}, []);

	// One sandbox per agent: once one is attached the section disappears.
	if (attachedSandboxIds.length > 0 || allSandboxes.length === 0) return null;

	return (
		<div>
			<h3 className="mb-3 font-mono text-[10.5px] font-semibold tracking-[0.09em] text-label dark:text-panel-dim">
				SANDBOXES
			</h3>
			<div className="content-start grid md:grid-cols-2 grid-cols-1 gap-x-2.5 gap-y-2">
				{allSandboxes.map((sandbox) => (
					<AvailableSandboxCard
						key={sandbox.id}
						sandbox={sandbox}
						onAdd={(sandboxId) => {
							onAddSandbox(sandboxId);
							onOpenChange(false);
						}}
					/>
				))}
			</div>
		</div>
	);
}

function MCPServerSection({
	attachedServerIds,
	onOpenChange,
	onAddServer,
}: {
	attachedServerIds: string[];
	onOpenChange: (open: boolean) => void;
	onAddServer: (serverId: string) => void;
}) {
	const router = useRouter();
	const [allServers, setAllServers] = useState<MCPServer[]>([]);
	const [isLoading, setIsLoading] = useState(true);

	useEffect(() => {
		api.get("/mcp-servers").then((res) => {
			setAllServers(res.data);
			setIsLoading(false);
		});
	}, []);

	const availableServers = useMemo(() => {
		const enabledIds = new Set(attachedServerIds);
		return allServers.filter((server) => !enabledIds.has(server.id));
	}, [allServers, attachedServerIds]);

	const handleServerAdded = (addedServerId: string) => {
		onAddServer(addedServerId);

		if (
			shouldCloseAddToolDialogAfterServerAdded(
				availableServers.map((server) => server.id),
				addedServerId,
			)
		) {
			onOpenChange(false);
		}
	};

	if (isLoading) {
		return (
			<div>
				<h3 className="mb-3 font-mono text-[10.5px] font-semibold tracking-[0.09em] text-label dark:text-panel-dim">
					MCP SERVERS
				</h3>
				<div className="content-start grid md:grid-cols-2 grid-cols-1 gap-x-2.5 gap-y-2">
					{[0, 1].map((i) => (
						<div key={i} className="h-[50px] animate-pulse rounded-[10px] border border-hairline bg-sidebar dark:border-white/10 dark:bg-white/5" />
					))}
				</div>
			</div>
		);
	}

	return (
		<div>
			<h3 className="mb-3 font-mono text-[10.5px] font-semibold tracking-[0.09em] text-label dark:text-panel-dim animate-in fade-in duration-300">
				MCP SERVERS
			</h3>
			{availableServers.length > 0 ? (
				<div className="content-start grid md:grid-cols-2 grid-cols-1 gap-x-2.5 gap-y-2 animate-in fade-in duration-300">
					{availableServers.map((server, i) => (
						<div
							key={server.id}
							className="animate-in fade-in slide-in-from-bottom-3 duration-400"
							style={{ animationDelay: `${i * 50}ms`, animationFillMode: "both" }}
						>
							<AvailableMCPServerCard
								server={server}
								onAdd={handleServerAdded}
							/>
						</div>
					))}
				</div>
			) : (
				<div className="text-center py-6 animate-in fade-in duration-300">
					{allServers.length === 0 ? (
						<>
							<p className="mb-4 text-center text-[13px] text-label dark:text-panel-dim">
								No MCP servers found. Start by adding a MCP server to your
								workspace.
							</p>
							<DialogButton
								variant="outline"
								onClick={() => { router.push("/mcp-servers"); }}
							>
								Add MCP server
							</DialogButton>
						</>
					) : (
						<p className="text-[13px] text-label dark:text-panel-dim">
							All workspace servers are already enabled for this agent.
						</p>
					)}
				</div>
			)}
		</div>
	);
}

export default function AddAgentToolDialog({
	open,
	onOpenChange,
	attachedServerIds,
	attachedSandboxIds,
	onAddServer,
	onAddSandbox,
}: AddAgentToolDialogProps) {
	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="sm:max-w-[560px]">
				<DialogHeader>
					<DialogTitle>Add tool</DialogTitle>
					<DialogDescription>
						Extend your agent&apos;s capabilities
					</DialogDescription>
				</DialogHeader>
				<div className="overflow-y-auto max-h-[450px] space-y-6 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
					<MCPServerSection
						attachedServerIds={attachedServerIds}
						onOpenChange={onOpenChange}
						onAddServer={onAddServer}
					/>
					<SandboxSection
						attachedSandboxIds={attachedSandboxIds}
						onOpenChange={onOpenChange}
						onAddSandbox={onAddSandbox}
					/>
				</div>
			</DialogContent>
		</Dialog>
	);
}
