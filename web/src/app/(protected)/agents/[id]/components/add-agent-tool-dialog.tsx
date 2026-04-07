"use client";

import { useState, useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";
import Image from "next/image";
import { Plus } from "lucide-react";
import { api } from "@/lib/api/client";
import { MCPServer } from "@/types/mcp-servers";
import { Agent } from "@/types/agents";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";

interface AddAgentToolDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	agent: Agent;
	onServerAdded?: () => void;
	onSandboxToggled?: () => void;
	onSaving?: () => void;
	onSaved?: () => void;
}

interface AvailableMCPServerCardProps {
	server: MCPServer;
	agentId: string;
	onAdd: () => void;
	onSaving?: () => void;
	onSaved?: () => void;
}

function AvailableMCPServerCard({
	server,
	agentId,
	onAdd,
	onSaving,
	onSaved,
}: AvailableMCPServerCardProps) {
	const [isAdding, setIsAdding] = useState(false);

	const handleAdd = async () => {
		setIsAdding(true);
		onSaving?.();
		try {
			await api.post(`/agents/${agentId}/mcp-servers/${server.id}`, {});
			onAdd();
			onSaved?.();
		} catch (error) {
			console.error("Failed to add MCP server to agent:", error);
			onSaved?.();
		} finally {
			setIsAdding(false);
		}
	};

	return (
		<div className="flex items-center gap-3 px-4 py-3 rounded-2xl border-[1.5px] border-[#E0E8E4] dark:border-white/10 bg-white dark:bg-white/5 hover:bg-sidebar-hover transition-colors">
			<Image
				src={
					server.iconUrl ??
					"https://storage.googleapis.com/choose-assets/mcp.png"
				}
				alt={server.name}
				width={24}
				height={24}
				className="shrink-0 rounded-md"
			/>
			<div className="min-w-0 flex-1">
				<h3 className="font-[family-name:var(--font-dm-sans)] text-[14px] font-semibold text-[#1E2D28] dark:text-foreground truncate">{server.name}</h3>
			</div>
			<button
				className="w-8 h-8 rounded-full bg-white dark:bg-white/10 border-[1.5px] border-[#E0E8E4] dark:border-white/10 flex items-center justify-center cursor-pointer transition-colors hover:bg-[#EDF4F0] dark:hover:bg-white/15 disabled:opacity-50"
				onClick={handleAdd}
				disabled={isAdding}
			>
				<Plus className="w-3.5 h-3.5 text-[#6B7F76]" />
			</button>
		</div>
	);
}

function BuiltInCapabilities({
	agent,
	sandboxAvailable,
	onSandboxToggled,
	onSaving,
	onSaved,
}: {
	agent: Agent;
	sandboxAvailable: boolean;
	onSandboxToggled?: () => void;
	onSaving?: () => void;
	onSaved?: () => void;
}) {
	const [sandboxEnabled, setSandboxEnabled] = useState(agent.sandbox);

	if (!sandboxAvailable) return null;

	const handleSandboxToggle = async (checked: boolean) => {
		setSandboxEnabled(checked);
		onSaving?.();
		try {
			await api.patch(`/agents/${agent.id}`, { sandbox: checked });
			onSandboxToggled?.();
			onSaved?.();
		} catch (error) {
			console.error("Failed to toggle sandbox:", error);
			setSandboxEnabled(!checked);
			onSaved?.();
		}
	};

	return (
		<div>
			<h3 className="font-[family-name:var(--font-dm-sans)] text-[14px] font-semibold text-[#8FA89E] dark:text-muted-foreground mb-3">
				Built-in capabilities
			</h3>
			<div className="flex items-center gap-3 px-4 py-3 rounded-2xl border-[1.5px] border-[#E0E8E4] dark:border-white/10 bg-white dark:bg-white/5">
				<div className="flex items-center justify-center w-9 h-9 rounded-lg shrink-0 overflow-hidden">
					<Image
						width={36}
						height={36}
						src="https://storage.googleapis.com/choose-assets/terminal.png"
						alt="Code execution"
						className="object-cover"
					/>
				</div>
				<div className="flex-1 min-w-0">
					<h4 className="font-[family-name:var(--font-dm-sans)] text-[14px] font-semibold text-[#1E2D28] dark:text-foreground">Code execution</h4>
					<p className="font-[family-name:var(--font-dm-sans)] text-[12px] text-[#8FA89E] dark:text-muted-foreground">
						Run Python in a sandboxed environment
					</p>
				</div>
				<Switch
					className="cursor-pointer"
					checked={sandboxEnabled}
					onCheckedChange={handleSandboxToggle}
				/>
			</div>
		</div>
	);
}

function MCPServerSection({
	agent,
	onServerAdded,
	onSaving,
	onSaved,
}: {
	agent: Agent;
	onServerAdded?: () => void;
	onSaving?: () => void;
	onSaved?: () => void;
}) {
	const router = useRouter();
	const [allServers, setAllServers] = useState<MCPServer[]>([]);
	const [isLoading, setIsLoading] = useState(true);

	useEffect(() => {
		setIsLoading(true);
		api.get("/mcp-servers").then((res) => {
			setAllServers(res.data);
			setIsLoading(false);
		});
	}, []);

	const availableServers = useMemo(() => {
		const enabledIds = new Set(
			agent.mcpServers?.map((s) => s.mcpServerId) || [],
		);
		return allServers.filter((server) => !enabledIds.has(server.id));
	}, [allServers, agent.mcpServers]);

	const handleServerAdded = () => {
		onServerAdded?.();
		api.get("/mcp-servers").then((res) => {
			setAllServers(res.data);
		});
	};

	if (isLoading) {
		return (
			<div>
				<h3 className="font-[family-name:var(--font-dm-sans)] text-[14px] font-semibold text-[#8FA89E] dark:text-muted-foreground mb-3">
					MCP servers
				</h3>
				<div className="content-start grid md:grid-cols-2 grid-cols-1 gap-x-2.5 gap-y-2">
					{[0, 1].map((i) => (
						<div key={i} className="h-[50px] rounded-2xl border-[1.5px] border-[#E0E8E4] dark:border-white/10 bg-[#FAFCFB] dark:bg-white/5 animate-pulse" />
					))}
				</div>
			</div>
		);
	}

	return (
		<div>
			<h3 className="font-[family-name:var(--font-dm-sans)] text-[14px] font-semibold text-[#8FA89E] dark:text-muted-foreground mb-3 animate-in fade-in duration-300">
				MCP servers
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
								agentId={agent.id}
								onAdd={handleServerAdded}
								onSaving={onSaving}
								onSaved={onSaved}
							/>
						</div>
					))}
				</div>
			) : (
				<div className="text-center py-6 animate-in fade-in duration-300">
					{allServers.length === 0 ? (
						<>
							<p className="font-[family-name:var(--font-dm-sans)] text-[13px] text-[#8FA89E] dark:text-muted-foreground text-center mb-4">
								No MCP servers found. Start by adding a MCP server to your
								workspace.
							</p>
							<button
								className="font-[family-name:var(--font-dm-sans)] px-5 py-2.5 rounded-full border-[1.5px] border-[#E0E8E4] dark:border-white/10 bg-white dark:bg-transparent text-[13px] font-semibold text-[#6B7F76] dark:text-muted-foreground cursor-pointer transition-colors hover:border-[#A3B5AD]"
								onClick={() => router.push("/mcp-servers")}
							>
								Add MCP Server
							</button>
						</>
					) : (
						<p className="font-[family-name:var(--font-dm-sans)] text-[13px] text-[#8FA89E] dark:text-muted-foreground">
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
	agent,
	onServerAdded,
	onSandboxToggled,
	onSaving,
	onSaved,
}: AddAgentToolDialogProps) {
	const [sandboxAvailable, setSandboxAvailable] = useState(false);

	useEffect(() => {
		if (open) {
			api.get("/sandbox/status").then((res) => {
				setSandboxAvailable(res.data.enabled);
			});
		}
	}, [open]);

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="sm:max-w-[560px]">
				<DialogHeader className="mb-1">
					<DialogTitle>Add tool</DialogTitle>
					<DialogDescription className="font-[family-name:var(--font-dm-sans)] text-[14px] text-[#A3B5AD] dark:text-muted-foreground">
						Extend your agent&apos;s capabilities
					</DialogDescription>
				</DialogHeader>
				<div className="overflow-y-auto max-h-[450px] space-y-7 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
					<MCPServerSection
						agent={agent}
						onServerAdded={onServerAdded}
						onSaving={onSaving}
						onSaved={onSaved}
					/>
					{sandboxAvailable && <div className="border-t border-[#E0E8E4] dark:border-white/10" />}
					<BuiltInCapabilities
						agent={agent}
						sandboxAvailable={sandboxAvailable}
						onSandboxToggled={onSandboxToggled}
						onSaving={onSaving}
						onSaved={onSaved}
					/>
				</div>
			</DialogContent>
		</Dialog>
	);
}
