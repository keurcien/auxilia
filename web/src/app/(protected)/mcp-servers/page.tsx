"use client";

import { useState } from "react";
import MCPServerList from "@/app/(protected)/mcp-servers/components/mcp-server-list";
import MCPServerDialog from "@/app/(protected)/mcp-servers/components/mcp-server-dialog";
import { MCPServer } from "@/types/mcp-servers";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function MCPServersPage() {
	const [dialogOpen, setDialogOpen] = useState(false);
	const [editServer, setEditServer] = useState<MCPServer | null>(null);

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
		<div className="mx-auto min-h-full w-full max-w-5xl px-4 pb-20 @min-screen-md/layout:px-8 @min-screen-xl/layout:max-w-6xl">
			<div className="flex items-center justify-between my-8">
				<h1 className="text-3xl font-bold text-card-foreground">
					Your workspace MCP servers
				</h1>
				<Button
					onClick={handleAddServer}
					className="flex items-center gap-2 px-4 py-2 bg-primary text-sm font-medium text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors cursor-pointer"
				>
					<Plus className="w-4 h-4" />
					Add MCP Server
				</Button>
			</div>
			<MCPServerList onServerClick={handleEditServer} />

			<MCPServerDialog
				open={dialogOpen}
				onOpenChange={handleDialogChange}
				server={editServer}
			/>
		</div>
	);
}
