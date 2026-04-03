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
import { Card, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
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
		<Card className="border border-border/60 shadow-none rounded-md overflow-hidden group justify-center py-2 h-[50px]">
			<CardHeader className="gap-0 px-4">
				<div className="flex w-full min-w-0 items-center justify-between">
					<div className="flex w-full min-w-0 items-center gap-3">
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
							<h3 className="text-sm font-medium truncate">{server.name}</h3>
						</div>

						<Button
							variant="ghost"
							size="icon"
							className="cursor-pointer"
							onClick={handleAdd}
							disabled={isAdding}
						>
							<Plus className="w-4 h-4" />
						</Button>
					</div>
				</div>
			</CardHeader>
		</Card>
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
			<h3 className="text-sm font-medium text-muted-foreground mb-3">
				Built-in capabilities
			</h3>
			<Card className="border border-border/60 shadow-none rounded-md py-3 px-4">
				<div className="flex items-center gap-3">
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
						<h4 className="text-sm font-medium">Code execution</h4>
						<p className="text-xs text-muted-foreground">
							Run Python in a sandboxed environment
						</p>
					</div>
					<Switch
						className="cursor-pointer"
						checked={sandboxEnabled}
						onCheckedChange={handleSandboxToggle}
					/>
				</div>
			</Card>
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

	useEffect(() => {
		api.get("/mcp-servers").then((res) => {
			setAllServers(res.data);
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

	return (
		<div>
			<h3 className="text-sm font-medium text-muted-foreground mb-3">
				MCP servers
			</h3>
			{availableServers.length > 0 ? (
				<div className="content-start grid md:grid-cols-2 grid-cols-1 gap-x-2.5 gap-y-2">
					{availableServers.map((server) => (
						<AvailableMCPServerCard
							key={server.id}
							server={server}
							agentId={agent.id}
							onAdd={handleServerAdded}
							onSaving={onSaving}
							onSaved={onSaved}
						/>
					))}
				</div>
			) : (
				<div className="text-center py-6 text-muted-foreground">
					{allServers.length === 0 ? (
						<>
							<p className="text-sm text-center mb-4">
								No MCP servers found. Start by adding a MCP server to your
								workspace.
							</p>
							<Button
								variant="outline"
								size="sm"
								className="mt-2 cursor-pointer"
								onClick={() => router.push("/mcp-servers")}
							>
								Add MCP Server
							</Button>
						</>
					) : (
						<p className="text-sm">
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
			<DialogContent className="sm:max-w-[600px] max-h-[600px]">
				<DialogHeader>
					<DialogTitle>Add tool</DialogTitle>
					<DialogDescription>
						Extend your agent&apos;s capabilities
					</DialogDescription>
				</DialogHeader>
				<div className="py-2 overflow-y-auto max-h-[450px] space-y-8 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
					<MCPServerSection
						agent={agent}
						onServerAdded={onServerAdded}
						onSaving={onSaving}
						onSaved={onSaved}
					/>
					{sandboxAvailable && <Separator />}
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
