"use client";

import {
	useEffect,
	useRef,
	useState,
	type DragEvent,
	type KeyboardEvent,
} from "react";
import {
	ChevronDownIcon,
	GripVerticalIcon,
	ListOrderedIcon,
	PencilIcon,
	Trash2Icon,
} from "lucide-react";

import {
	Collapsible,
	CollapsibleContent,
	CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import type { QueuedPrompt } from "@/types/runs";

type PromptQueueProps = {
	items: QueuedPrompt[];
	editingId: string | null;
	busyId: string | null;
	onEdit: (item: QueuedPrompt) => void;
	onRemove: (id: string) => Promise<void>;
	onReorder: (orderedIds: string[]) => Promise<void>;
};

export function PromptQueue({
	items,
	editingId,
	busyId,
	onEdit,
	onRemove,
	onReorder,
}: PromptQueueProps) {
	const [open, setOpen] = useState(true);
	const [draggedId, setDraggedId] = useState<string | null>(null);
	const [overId, setOverId] = useState<string | null>(null);
	const [announcement, setAnnouncement] = useState({
		message: "",
		revision: 0,
	});
	const listRef = useRef<HTMLDivElement | null>(null);
	// Ids rendered on the previous commit. A new id means a prompt was
	// appended: scroll the list so the newest items stay in view. Removals
	// and reorders (same ids) leave the scroll position alone.
	const knownIds = useRef<Set<string>>(new Set());

	useEffect(() => {
		const appended = items.some((item) => !knownIds.current.has(item.id));
		knownIds.current = new Set(items.map((item) => item.id));
		if (!appended || !open) return;
		const list = listRef.current;
		if (!list) return;
		list.scrollTo({ top: list.scrollHeight, behavior: "smooth" });
	}, [items, open]);

	if (items.length === 0) return null;

	const move = (id: string, direction: -1 | 1) => {
		const from = items.findIndex((item) => item.id === id);
		const to = from + direction;
		if (from < 0 || to < 0 || to >= items.length) return;
		const ids = items.map((item) => item.id);
		const fromId = ids.at(from);
		const toId = ids.at(to);
		if (!fromId || !toId) return;
		const reordered = ids.map((id, index) => {
			if (index === from) return toId;
			if (index === to) return fromId;
			return id;
		});
		setAnnouncement((current) => ({
			message: `Moved prompt to position ${to + 1} of ${items.length}.`,
			revision: current.revision + 1,
		}));
		void onReorder(reordered);
	};

	const drop = (event: DragEvent, targetId: string) => {
		event.preventDefault();
		if (!draggedId || draggedId === targetId) {
			setDraggedId(null);
			setOverId(null);
			return;
		}
		const ids = items.map((item) => item.id);
		const from = ids.indexOf(draggedId);
		const to = ids.indexOf(targetId);
		ids.splice(to, 0, ids.splice(from, 1)[0]);
		setAnnouncement((current) => ({
			message: `Moved prompt to position ${to + 1} of ${items.length}.`,
			revision: current.revision + 1,
		}));
		setDraggedId(null);
		setOverId(null);
		void onReorder(ids);
	};

	const handleGripKeyDown = (
		event: KeyboardEvent<HTMLButtonElement>,
		id: string,
	) => {
		if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
		event.preventDefault();
		move(id, event.key === "ArrowUp" ? -1 : 1);
	};

	return (
		<Collapsible
			open={open}
			onOpenChange={setOpen}
			className="mb-2 overflow-hidden rounded-xl border border-petrol/20 bg-petrol/[0.035] shadow-[0_8px_28px_-24px_var(--petrol)] dark:bg-white/[0.035]"
		>
			<span
				key={announcement.revision}
				className="sr-only"
				role="status"
				aria-live="polite"
			>
				{announcement.message}
			</span>
			<CollapsibleTrigger asChild>
				<button
					type="button"
					className="flex w-full cursor-pointer items-center gap-2.5 px-3.5 py-2.5 text-left transition-colors hover:bg-petrol/[0.055] dark:hover:bg-white/[0.045]"
				>
					<span className="flex size-7 items-center justify-center rounded-lg bg-petrol/10 text-petrol">
						<ListOrderedIcon className="size-3.5" />
					</span>
					<span className="flex-1 text-[12px] font-semibold tracking-[0.01em] text-foreground">
						{items.length} prompt{items.length > 1 ? "s" : ""} queued
					</span>
					<span className="text-[11px] text-meta dark:text-panel-dim">
						Runs in order
					</span>
					<ChevronDownIcon
						className={cn(
							"size-4 text-meta transition-transform duration-200",
							open && "rotate-180",
						)}
					/>
				</button>
			</CollapsibleTrigger>
			<CollapsibleContent className="border-t border-petrol/10">
				<div
					ref={listRef}
					className="max-h-48 space-y-1 overflow-y-auto p-2"
				>
					{items.map((item, index) => {
						const isEditing = editingId === item.id;
						const isBusy = busyId === item.id;
						return (
							<div
								key={item.id}
								draggable={!isBusy}
								onDragStart={(event) => {
									setDraggedId(item.id);
									event.dataTransfer.effectAllowed = "move";
								}}
								onDragOver={(event) => {
									event.preventDefault();
									setOverId(item.id);
								}}
								onDragLeave={() => {
									setOverId((current) =>
										current === item.id ? null : current,
									);
								}}
								onDrop={(event) => {
									drop(event, item.id);
								}}
								onDragEnd={() => {
									setDraggedId(null);
									setOverId(null);
								}}
								className={cn(
									"group flex items-center gap-1.5 rounded-lg border px-2 py-1.5 transition-all",
									isEditing
										? "border-sky-400/50 bg-sky-500/[0.08]"
										: "border-transparent bg-card/70 hover:border-petrol/15 hover:bg-card",
									overId === item.id && "translate-y-0.5 border-petrol/40",
									draggedId === item.id && "opacity-45",
								)}
							>
								<button
									type="button"
									title="Drag to reorder. Use Arrow Up or Arrow Down from this handle."
									aria-label={`Reorder queued prompt ${index + 1}`}
									onKeyDown={(event) => {
										handleGripKeyDown(event, item.id);
									}}
									className="flex size-7 shrink-0 cursor-grab items-center justify-center rounded-md text-ghost transition-colors hover:bg-hover hover:text-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-petrol/40 active:cursor-grabbing"
								>
									<GripVerticalIcon className="size-4" />
								</button>
								<span className="w-5 shrink-0 text-center font-mono text-[10px] font-semibold text-meta">
									{index + 1}
								</span>
								<p className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-foreground/85">
									{item.text}
								</p>
								<button
									type="button"
									disabled={isBusy}
									onClick={() => {
										onEdit(item);
									}}
									aria-label="Edit queued prompt"
									className="flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-md text-meta opacity-70 transition-all hover:bg-sky-500/10 hover:text-sky-600 disabled:cursor-wait disabled:opacity-40 sm:opacity-0 sm:group-hover:opacity-100 sm:focus-visible:opacity-100"
								>
									<PencilIcon className="size-3.5" />
								</button>
								<button
									type="button"
									disabled={isBusy}
									onClick={() => {
										void onRemove(item.id);
									}}
									aria-label="Remove queued prompt"
									className="flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-md text-meta opacity-70 transition-all hover:bg-destructive/10 hover:text-destructive disabled:cursor-wait disabled:opacity-40 sm:opacity-0 sm:group-hover:opacity-100 sm:focus-visible:opacity-100"
								>
									<Trash2Icon className="size-3.5" />
								</button>
							</div>
						);
					})}
				</div>
			</CollapsibleContent>
		</Collapsible>
	);
}
