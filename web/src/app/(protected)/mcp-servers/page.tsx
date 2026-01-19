"use client";

import { useState } from "react";
import MCPServerList from "@/app/(protected)/mcp-servers/components/mcp-server-list";
import AddMCPServerDialog from "@/app/(protected)/mcp-servers/components/add-mcp-server-dialog";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function MCPServersPage() {
	const [isDialogOpen, setIsDialogOpen] = useState(false);

	const handleAddServer = () => {
		setIsDialogOpen(true);
	};

	return (
		<div className="mx-auto min-h-full w-full max-w-5xl px-4 pb-20 @min-screen-md/layout:px-8 @min-screen-xl/layout:max-w-6xl">
			<div className="flex items-center justify-between my-8">
				<h1 className="text-3xl font-bold text-gray-900">
					Your workspace MCP servers
				</h1>
				<Button
					onClick={handleAddServer}
					className="flex items-center gap-2 px-4 py-2 bg-black text-sm font-medium text-white rounded-lg hover:bg-gray-800 transition-colors cursor-pointer"
				>
					<Plus className="w-4 h-4" />
					Add MCP Server
				</Button>
			</div>
			<MCPServerList />

			<AddMCPServerDialog open={isDialogOpen} onOpenChange={setIsDialogOpen} />
		</div>
	);
}
