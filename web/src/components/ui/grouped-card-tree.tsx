"use client";

import { useState, type ReactNode } from "react";
import { ChevronRight, Folder } from "lucide-react";
import type { GroupNode, GroupTree } from "@/lib/groups";
import { cn } from "@/lib/utils";

function CardGrid<T>({
	items,
	renderItem,
}: {
	items: T[];
	renderItem: (item: T, index: number) => ReactNode;
}) {
	return (
		<div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
			{items.map(renderItem)}
		</div>
	);
}

function GroupedCardNode<T>({
	node,
	renderItem,
	storageKey,
}: {
	node: GroupNode<T>;
	renderItem: (item: T, index: number) => ReactNode;
	storageKey: string;
}) {
	const [expanded, setExpanded] = useState(() => {
		try {
			return localStorage.getItem(storageKey) !== "0";
		} catch {
			return true;
		}
	});

	const toggle = () => {
		setExpanded((current) => {
			const next = !current;
			try {
				localStorage.setItem(storageKey, next ? "1" : "0");
			} catch {
				// The in-session state still works when persistence is unavailable.
			}
			return next;
		});
	};

	return (
		<section className="animate-in fade-in duration-300">
			<button
				type="button"
				aria-expanded={expanded}
				onClick={toggle}
				style={{ paddingLeft: `${node.depth * 18}px` }}
				className="group mb-3 flex w-full cursor-pointer items-center gap-2 py-1 text-left"
			>
				<ChevronRight
					className={cn(
						"size-3.5 shrink-0 text-meta transition-transform",
						expanded && "rotate-90",
					)}
				/>
				<Folder className="size-4 shrink-0 text-meta" />
				<h2 className="whitespace-nowrap text-[13.5px] font-bold tracking-[-0.01em] text-foreground">
					{node.name}
				</h2>
				<span className="font-mono text-[11px] text-meta">{node.count}</span>
				<div className="h-px flex-1 bg-[#E8EFE9] dark:bg-white/10" />
			</button>
			{expanded && (
				<div className="mb-6">
					{node.items.length > 0 && (
						<div
							className="mb-4"
							style={{ paddingLeft: `${(node.depth + 1) * 18}px` }}
						>
							<CardGrid items={node.items} renderItem={renderItem} />
						</div>
					)}
					{node.children.map((child) => (
						<GroupedCardNode
							key={child.path}
							node={child}
							renderItem={renderItem}
							storageKey={`${storageKey}:${child.path}`}
						/>
					))}
				</div>
			)}
		</section>
	);
}

export function GroupedCardTree<T>({
	tree,
	renderItem,
	storageKey,
}: {
	tree: GroupTree<T>;
	renderItem: (item: T, index: number) => ReactNode;
	storageKey: string;
}) {
	if (tree.groups.length === 0) {
		return <CardGrid items={tree.ungrouped} renderItem={renderItem} />;
	}
	return (
		<>
			{tree.groups.map((group) => (
				<GroupedCardNode
					key={group.path}
					node={group}
					renderItem={renderItem}
					storageKey={`${storageKey}:${group.path}`}
				/>
			))}
			{tree.ungrouped.length > 0 && (
				<GroupedCardNode
					node={{
						name: "Others",
						path: "__ungrouped__",
						depth: 0,
						items: tree.ungrouped,
						children: [],
						count: tree.ungrouped.length,
					}}
					renderItem={renderItem}
					storageKey={`${storageKey}:__ungrouped__`}
				/>
			)}
		</>
	);
}
