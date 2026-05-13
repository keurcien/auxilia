"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { api } from "@/lib/api/client";
import { PageContainer } from "@/components/layout/page-container";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import { ThreadSourceBadge } from "@/components/ui/thread-source-badge";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import type { Agent } from "@/types/agents";
import type { AgentThread } from "@/types/threads";

function initials(name: string | null, email: string | null): string {
	const source = name || email || "?";
	const parts = source.trim().split(/\s+/);
	if (parts.length >= 2) {
		return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
	}
	return source.substring(0, 2).toUpperCase();
}

function formatDate(dateStr: string): string {
	const diff = Date.now() - new Date(dateStr).getTime();
	const minutes = Math.floor(diff / (1000 * 60));
	if (minutes < 1) return "just now";
	if (minutes < 60) return `${minutes}m ago`;
	const hours = Math.floor(minutes / 60);
	if (hours < 24) return `${hours}h ago`;
	const days = Math.floor(hours / 24);
	if (days < 7) return `${days}d ago`;
	return new Date(dateStr).toLocaleDateString("en-US", {
		month: "short",
		day: "numeric",
		year: "numeric",
	});
}

export default function AgentThreadsPage() {
	const params = useParams();
	const router = useRouter();
	const agentId = params.id as string;
	const [agent, setAgent] = useState<Agent | null>(null);
	const [threads, setThreads] = useState<AgentThread[]>([]);
	const [isLoading, setIsLoading] = useState(true);
	const [forbiddenOpen, setForbiddenOpen] = useState(false);

	useEffect(() => {
		const fetch = async () => {
			try {
				const [agentRes, threadsRes] = await Promise.all([
					api.get<Agent>(`/agents/${agentId}`),
					api.get<AgentThread[]>(`/agents/${agentId}/threads`),
				]);
				setAgent(agentRes.data);
				setThreads(threadsRes.data);
			} catch (error: unknown) {
				if (
					error instanceof Object &&
					"status" in error &&
					(error.status === 403 || error.status === 401)
				) {
					setForbiddenOpen(true);
				} else {
					console.error("Error fetching agent threads:", error);
				}
			} finally {
				setIsLoading(false);
			}
		};
		void fetch();
	}, [agentId]);

	return (
		<PageContainer>
			<ForbiddenErrorDialog
				open={forbiddenOpen}
				onOpenChange={(open) => {
					setForbiddenOpen(open);
					if (!open) router.push(`/agents/${agentId}`);
				}}
				title="Insufficient privileges"
				message="You don't have permission to view this agent's threads."
			/>

			<div className="flex items-start gap-4 my-8">
				<button
					type="button"
					onClick={() => {
						router.push(`/agents/${agentId}`);
					}}
					className="shrink-0 w-10 h-10 rounded-full bg-[#F5F8F6] dark:bg-white/10 flex items-center justify-center cursor-pointer transition-colors hover:bg-[#EDF4F0] dark:hover:bg-white/15"
					aria-label="Back to agent"
				>
					<ArrowLeft className="w-[18px] h-[18px] text-[#6B7F76]" />
				</button>

				<div className="flex-1 min-w-0">
					<div className="px-5 mb-7 flex items-center justify-between gap-4">
						<h1 className="font-[family-name:var(--font-jakarta-sans)] font-extrabold text-[28px] tracking-[-0.03em] text-[#111111] dark:text-white truncate">
							Thread history
						</h1>
						{agent && (
							<div className="flex items-center gap-2 shrink-0 min-w-0">
								<AgentAvatar
									color={agent.color}
									emoji={agent.emoji}
									size="sm"
								/>
								<h2 className="text-md font-bold truncate">{agent.name}</h2>
							</div>
						)}
					</div>

					{isLoading ? null : threads.length === 0 ? (
						<div className="text-center py-16 text-[14px] text-[#A3B5AD] dark:text-muted-foreground font-medium">
							No threads yet for this agent.
						</div>
					) : (
						<>
							<div className="flex items-center py-3 pl-[76px] pr-5 mb-1 font-[family-name:var(--font-dm-sans)] animate-in fade-in duration-300">
								<div className="w-[220px] shrink-0 text-[11px] font-semibold text-[#B8C8C0] dark:text-muted-foreground uppercase tracking-[0.06em]">
									User
								</div>
								<div className="w-[440px] shrink-0 text-[11px] font-semibold text-[#B8C8C0] dark:text-muted-foreground uppercase tracking-[0.06em]">
									First message
								</div>
								<div className="w-[120px] shrink-0 text-[11px] font-semibold text-[#B8C8C0] dark:text-muted-foreground uppercase tracking-[0.06em]">
									Source
								</div>
								<div className="w-[110px] shrink-0 text-[11px] font-semibold text-[#B8C8C0] dark:text-muted-foreground uppercase tracking-[0.06em]">
									Created
								</div>
							</div>

							<div>
								{threads.map((thread, i) => (
									<Link
										key={thread.id}
										href={`/agents/${agentId}/chat/${thread.id}`}
										className="group flex items-center py-3.5 px-5 rounded-[18px] mb-1 transition-all duration-200 hover:bg-[#F8FAF9] dark:hover:bg-white/5 hover:translate-x-1 animate-in fade-in slide-in-from-bottom-3"
										style={{
											animationDelay: `${i * 30}ms`,
											animationFillMode: "both",
										}}
									>
										<div className="shrink-0 w-[42px] h-[42px] rounded-full bg-[#F0F3F2] dark:bg-white/10 border-[1.5px] border-[#E0E8E4] dark:border-white/10 flex items-center justify-center text-[13.5px] font-bold text-[#6B7F76] dark:text-muted-foreground transition-transform duration-300 group-hover:scale-105">
											{initials(thread.userName, thread.userEmail)}
										</div>

										<div className="w-[220px] shrink-0 min-w-0 ml-3.5 font-[family-name:var(--font-dm-sans)]">
											<div className="text-[14px] font-semibold text-[#1E2D28] dark:text-foreground truncate">
												{thread.userName || "Unnamed"}
											</div>
											<div className="text-[12px] text-[#8FA89E] dark:text-muted-foreground font-medium truncate mt-0.5">
												{thread.userEmail}
											</div>
										</div>

										<div className="w-[440px] shrink-0 min-w-0 pr-4 font-[family-name:var(--font-dm-sans)] text-[13.5px] text-[#3F524B] dark:text-foreground/80 font-medium truncate">
											{thread.firstMessageContent || (
												<span className="italic text-[#A3B5AD]">
													No message
												</span>
											)}
										</div>

										<div className="w-[120px] shrink-0">
											<ThreadSourceBadge source={thread.source} />
										</div>

										<div className="w-[110px] shrink-0 font-[family-name:var(--font-dm-sans)] text-[13px] text-[#8FA89E] dark:text-muted-foreground font-medium">
											{formatDate(thread.createdAt)}
										</div>
									</Link>
								))}
							</div>
						</>
					)}
				</div>
			</div>
		</PageContainer>
	);
}
