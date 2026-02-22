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
				<h1 className="font-primary font-extrabold text-4xl tracking-tighter text-[#2A2F2D]">
					MCP servers
				</h1>
				<Button
					onClick={handleAddServer}
					className="flex items-center gap-2 py-5 bg-[#2A2F2D] text-base font-semibold text-white rounded-[14px] hover:opacity-90 transition-opacity cursor-pointer shadow-[0_4px_14px_rgba(118,181,160,0.14)] border-none"
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
