"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight } from "lucide-react";
import { Agent, AgentPermission } from "@/types/agents";
import { useMcpServersStore } from "@/stores/mcp-servers-store";
import {
	Dialog,
	DialogContent,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import Image from "next/image";

interface AgentCardProps {
	agent: Agent;
}

const PERMISSION_HIERARCHY: Record<AgentPermission, number> = {
	user: 0,
	editor: 1,
	admin: 2,
	owner: 3,
};

const ROLE_BADGE_CONFIG: Record<
	AgentPermission,
	{ label: string; bg: string; text: string; dot: string }
> = {
	owner: {
		label: "Owner",
		bg: "bg-[#E4EDE2] dark:bg-emerald-950",
		text: "text-[#4E7050] dark:text-emerald-300",
		dot: "bg-[#6B8F6B] dark:bg-emerald-400",
	},
	admin: {
		label: "Admin",
		bg: "bg-[#E4EDE2] dark:bg-emerald-950",
		text: "text-[#4E7050] dark:text-emerald-300",
		dot: "bg-[#6B8F6B] dark:bg-emerald-400",
	},
	editor: {
		label: "Editor",
		bg: "bg-[#F2EBDA] dark:bg-amber-950",
		text: "text-[#9A7B3C] dark:text-amber-300",
		dot: "bg-[#C4A04E] dark:bg-amber-400",
	},
	user: {
		label: "User",
		bg: "bg-[#EDEEE9] dark:bg-stone-800",
		text: "text-[#7D8077] dark:text-stone-400",
		dot: "bg-[#A3A79C] dark:bg-stone-500",
	},
};

function hasPermission(
	current: AgentPermission | null | undefined,
	required: AgentPermission,
): boolean {
	if (!current) return false;
	return PERMISSION_HIERARCHY[current] >= PERMISSION_HIERARCHY[required];
}

const NO_ACCESS_BADGE = {
	label: "No access",
	bg: "bg-[#F3E4E6] dark:bg-rose-950",
	text: "text-[#A35462] dark:text-rose-300",
	dot: "bg-[#C97080] dark:bg-rose-400",
};

export default function AgentCard({ agent }: AgentCardProps) {
	const router = useRouter();
	const [open, setOpen] = useState(false);
	const mcpServers = useMcpServersStore((state) => state.mcpServers);
	const hasAccess = !!agent.currentUserPermission;

	const resolvedServers = useMemo(() => {
		if (!agent.mcpServers) return [];
		return agent.mcpServers.map((s) => {
			const full = mcpServers.find((m) => m.id === s.id);
			return { id: s.id, name: full?.name ?? s.id, iconUrl: full?.iconUrl };
		});
	}, [agent.mcpServers, mcpServers]);

	const handleChat = () => {
		if (!hasPermission(agent.currentUserPermission, "user")) {
			alert("You don't have permission to chat with this agent.");
			return;
		}
		setOpen(false);
		router.push(`/agents/${agent.id}/chat`);
	};

	const handleEdit = () => {
		if (!hasPermission(agent.currentUserPermission, "editor")) {
			alert("You don't have permission to edit this agent.");
			return;
		}
		setOpen(false);
		router.push(`/agents/${agent.id}`);
	};

	return (
		<>
			<div
				className={`group flex flex-col gap-4 p-6 border rounded-2xl transition-all duration-200 h-full border-border bg-card shadow-sm ${
					hasAccess
						? "hover:shadow-md hover:-translate-y-0.5 cursor-pointer"
						: "cursor-default"
				}`}
				onClick={() => hasAccess && setOpen(true)}
			>
				<div className="flex items-start justify-between gap-3">
					<div className="flex items-center gap-3.5 min-w-0">
						<div className="flex items-center justify-center shrink-0 w-11 h-11 rounded-xl bg-muted text-[22px]">
							{agent.emoji || "🤖"}
						</div>
						<div className="min-w-0">
							<h2 className="text-[15px] font-semibold text-card-foreground leading-tight truncate">
								{agent.name}
							</h2>
							<p className="text-[13px] text-muted-foreground mt-0.5">
								@{agent.name.toLowerCase().replace(/\s+/g, "_")}
							</p>
						</div>
					</div>
					{(() => {
						const badge = agent.currentUserPermission
							? ROLE_BADGE_CONFIG[agent.currentUserPermission]
							: NO_ACCESS_BADGE;
						return (
							<span
								className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium shrink-0 ${badge.bg} ${badge.text}`}
							>
								<span
									className={`w-1.5 h-1.5 rounded-full shrink-0 ${badge.dot}`}
								/>
								{badge.label}
							</span>
						);
					})()}
				</div>
				<p className="text-[13.5px] leading-relaxed text-muted-foreground line-clamp-3 min-h-[4.5em]">
					{agent.description || "No description provided."}
				</p>
			</div>

			<Dialog open={open} onOpenChange={setOpen}>
				<DialogContent className="sm:max-w-[420px]" showCloseButton={false}>
					<DialogHeader>
						<div className="flex items-center gap-4 mb-4">
							<div className="flex items-center justify-center shrink-0 w-12 h-12 rounded-2xl bg-muted text-2xl">
								{agent.emoji || "🤖"}
							</div>
							<DialogTitle className="text-xl">{agent.name}</DialogTitle>
						</div>
					</DialogHeader>

					<div className="mb-4">
						<p className="text-xs font-bold text-muted-foreground mb-1">
							Description
						</p>
						<p className="text-sm text-muted-foreground wrap-break-word whitespace-pre-wrap">
							{agent.description || "No description provided."}
						</p>
					</div>

					{resolvedServers.length > 0 && (
						<div>
							<p className="text-xs font-bold text-muted-foreground mb-1">
								Tools
							</p>
							<div className="flex flex-wrap gap-2">
								{resolvedServers.map((server) => (
									<Image
										key={server.id}
										src={
											server.iconUrl ??
											"https://storage.googleapis.com/choose-assets/mcp.png"
										}
										alt={server.name}
										width={24}
										height={24}
										className="shrink-0 rounded-md"
									/>
								))}
							</div>
						</div>
					)}

					<div className="flex gap-3 pt-2">
						<Button
							variant="outline"
							className="flex-1 cursor-pointer"
							onClick={handleEdit}
						>
							Edit
						</Button>
						<Button className="flex-1 cursor-pointer" onClick={handleChat}>
							Chat
							<ArrowRight className="size-4 ml-1" />
						</Button>
					</div>
				</DialogContent>
			</Dialog>
		</>
	);
}
