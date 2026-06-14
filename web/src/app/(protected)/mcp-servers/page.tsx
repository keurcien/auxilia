"use client";

import { useState } from "react";
import MCPServerList from "@/app/(protected)/mcp-servers/components/mcp-server-list";
import MCPServerDialog from "@/app/(protected)/mcp-servers/components/mcp-server-dialog";
import { MCPServer } from "@/types/mcp-servers";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageContainer } from "@/components/layout/page-container";

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
		<PageContainer>
			<div className="flex items-center justify-between my-8 mb-7">
				<h1 className="font-[family-name:var(--font-jakarta-sans)] font-extrabold text-[32px] tracking-[-0.03em] text-[#111111] dark:text-white">
					MCP servers
				</h1>
				<Button
					onClick={handleAddServer}
					className="flex items-center gap-2 !px-6 !py-3 !h-auto bg-[#111111] dark:bg-white dark:text-[#111111] text-[14px] font-semibold font-[family-name:var(--font-dm-sans)] text-white rounded-full hover:bg-[#222222] dark:hover:bg-gray-100 transition-all cursor-pointer shadow-[0_4px_12px_-2px_rgba(0,0,0,0.15)] border-none"
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
		</PageContainer>
	);
}
