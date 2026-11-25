"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import { cn } from "@/lib/utils";
import type { BoundAgent } from "@/types/agents";

export interface UsedByItem {
	id: string;
	href: string;
	name: string;
	leading: ReactNode;
	meta?: ReactNode;
}

/**
 * What depends on a resource, as a block of its detail page: the agents an
 * MCP server or a skill is enabled on, the triggers that run an agent. Each
 * row opens the dependent.
 */
export function UsedByList({
	items,
	loading = false,
	emptyText,
	className,
}: {
	items: UsedByItem[];
	loading?: boolean;
	emptyText: ReactNode;
	className?: string;
}) {
	return (
		<div className={cn("flex flex-col", className)}>
			<div className="mb-3 flex min-h-[24px] shrink-0 items-center">
				<span className="text-[10.5px] font-semibold text-label dark:text-muted-foreground">
					Used by
					{!loading && (
						<span className="ml-1 text-meta dark:text-panel-dim">{items.length}</span>
					)}
				</span>
			</div>
			{loading ? (
				<div className="h-[42px] animate-pulse rounded-[10px] border border-border bg-card" />
			) : items.length === 0 ? (
				<div className="rounded-[10px] border border-dashed border-input px-4 py-6 text-center text-[13px] text-meta dark:text-panel-dim">
					{emptyText}
				</div>
			) : (
				<div className="overflow-hidden rounded-[10px] border border-border bg-card">
					{items.map((item) => (
						<Link
							key={item.id}
							href={item.href}
							className="flex items-center gap-3 border-b border-hairline px-4 py-2.5 transition-colors last:border-b-0 hover:bg-sidebar dark:border-white/5 dark:hover:bg-white/5"
						>
							{item.leading}
							<span className="min-w-0 flex-1 truncate text-[12.5px] font-semibold text-petrol">
								{item.name}
							</span>
							{item.meta && (
								<span className="max-w-[45%] shrink-0 truncate text-[11.5px] text-meta dark:text-panel-dim">
									{item.meta}
								</span>
							)}
							<ChevronRight className="size-3.5 shrink-0 text-faint dark:text-panel-dim" />
						</Link>
					))}
				</div>
			)}
		</div>
	);
}

export function agentUsedByItem(agent: BoundAgent): UsedByItem {
	return {
		id: agent.id,
		href: `/agents/${agent.id}`,
		name: agent.name,
		leading: (
			<AgentAvatar
				agentId={agent.id}
				name={agent.name}
				imageRevision={agent.imageRevision}
				color={agent.color}
				emoji={agent.emoji}
				size="xs"
			/>
		),
	};
}
