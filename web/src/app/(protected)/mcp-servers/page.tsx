"use client";

import { useState } from "react";
import MCPServerList from "@/app/(protected)/mcp-servers/components/mcp-server-list";
import MCPServerDialog from "@/app/(protected)/mcp-servers/components/mcp-server-dialog";
import { MCPServer } from "@/types/mcp-servers";
import { Plus } from "lucide-react";
import {
	WorkspacePage,
	WorkspaceTopBarButton,
} from "@/components/layout/workspace-page";

export default function MCPServersPage() {
	const [dialogOpen, setDialogOpen] = useState(false);
	const [editServer, setEditServer] = useState<MCPServer | null>(null);
	const [search, setSearch] = useState("");

	const handleAddServer = () => {
		setEditServer(null);
		setDialogOpen(true);
	};

	const handleEditServer = (server: MCPServer) => {
		setEditServer(server);
		setDialogOpen(true);
	};

	const handleDialogChange = (open: boolean) => {
		setDialogOpen(open);
		if (!open) setEditServer(null);
	};

	return (
		<WorkspacePage
			slug="mcp-servers"
			title="MCP servers"
			intro="Remote Model Context Protocol endpoints wired into your workspace."
			search={{
				placeholder: "Search servers…",
				value: search,
				onChange: setSearch,
			}}
			actions={
				<WorkspaceTopBarButton onClick={handleAddServer}>
					<Plus className="size-3.5" />
					Add MCP server
				</WorkspaceTopBarButton>
			}
		>
			<MCPServerList search={search} onServerClick={handleEditServer} />

			<MCPServerDialog
				open={dialogOpen}
				onOpenChange={handleDialogChange}
				server={editServer}
			/>
		</WorkspacePage>
	);
}
