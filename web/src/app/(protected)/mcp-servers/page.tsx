"use client";

import { useState } from "react";
import MCPServerList from "@/app/(protected)/mcp-servers/components/mcp-server-list";
import MCPServerDialog from "@/app/(protected)/mcp-servers/components/mcp-server-dialog";
import { MCPServer } from "@/types/mcp-servers";
import PageHeaderButton from "@/components/page-header-button";

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
				<h1 className="font-primary font-extrabold text-2xl md:text-4xl tracking-tighter text-[#2A2F2D] dark:text-white">
					MCP servers
				</h1>
				<PageHeaderButton onClick={handleAddServer}>
					Add MCP Server
				</PageHeaderButton>
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
