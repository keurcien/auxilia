"use client";

import { useState } from "react";
import MCPServerList from "@/app/(protected)/mcp-servers/components/mcp-server-list";
import MCPServerDialog from "@/app/(protected)/mcp-servers/components/mcp-server-dialog";
import { MCPServer } from "@/types/mcp-servers";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SearchBar } from "@/components/ui/search-bar";
import { PageContainer } from "@/components/layout/page-container";

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
		<PageContainer>
			<div className="flex flex-col gap-5 my-8 sm:flex-row sm:items-start sm:justify-between">
				<div className="min-w-0">
					<h1 className="font-[family-name:var(--font-jakarta-sans)] font-extrabold text-[32px] tracking-[-0.03em] text-[#111111] dark:text-white">
						MCP servers
					</h1>
					<p className="mt-1.5 font-[family-name:var(--font-dm-sans)] text-[15px] font-medium text-[#6B7F76] dark:text-muted-foreground">
						Remote Model Context Protocol endpoints wired into your workspace.
					</p>
				</div>

				<div className="flex items-center gap-3 shrink-0">
					<SearchBar
						placeholder="Search servers..."
						value={search}
						onChange={setSearch}
						hint="⌘K"
						className="w-full sm:w-72"
					/>
					<Button
						onClick={handleAddServer}
						className="flex items-center gap-2 px-6! py-3! h-auto! bg-[#111111] dark:bg-white dark:text-[#111111] text-[14px] font-semibold font-[family-name:var(--font-dm-sans)] text-white rounded-full hover:bg-[#222222] dark:hover:bg-gray-100 transition-all cursor-pointer shadow-[0_4px_12px_-2px_rgba(0,0,0,0.15)] border-none whitespace-nowrap"
					>
						<Plus className="w-4 h-4" />
						Add MCP server
					</Button>
				</div>
			</div>
			<MCPServerList search={search} onServerClick={handleEditServer} />

			<MCPServerDialog
				open={dialogOpen}
				onOpenChange={handleDialogChange}
				server={editServer}
			/>
		</PageContainer>
	);
}
