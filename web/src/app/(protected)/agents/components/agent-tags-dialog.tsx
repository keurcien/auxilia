"use client";

import { useEffect, useState } from "react";
import { Check, MoreVertical, Pencil, Plus, Trash2, X } from "lucide-react";
import { api } from "@/lib/api/client";
import { getApiErrorMessage } from "@/lib/api/errors";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { SageButton } from "@/components/ui/sage-button";
import { SageDropdownMenu } from "@/components/ui/sage-dropdown-menu";
import { useAgentsStore } from "@/stores/agents-store";
import { useUserStore } from "@/stores/user-store";
import { Agent, AgentTag } from "@/types/agents";
import NewTagDialog from "./new-tag-dialog";

interface AgentTagsDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	agent: Agent;
}

const byName = (a: AgentTag, b: AgentTag) => a.name.localeCompare(b.name);

export default function AgentTagsDialog({
	open,
	onOpenChange,
	agent,
}: AgentTagsDialogProps) {
	const updateAgent = useAgentsStore((state) => state.updateAgent);
	const applyTagUpdate = useAgentsStore((state) => state.applyTagUpdate);
	const applyTagRemoval = useAgentsStore((state) => state.applyTagRemoval);
	const user = useUserStore((state) => state.user);
	// Assigning is open to anyone who can open this dialog; creating, renaming
	// and deleting tags (the shared vocabulary) is workspace-admin only.
	const isWorkspaceAdmin = user?.role === "admin";

	const [tags, setTags] = useState<AgentTag[]>([]);
	const [selectedTagId, setSelectedTagId] = useState<string | null>(null);
	const [isAssigning, setIsAssigning] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [tagDialogOpen, setTagDialogOpen] = useState(false);
	const [editingTag, setEditingTag] = useState<AgentTag | null>(null);

	// Runs on open only — assigning a tag updates the agent in the store, and
	// re-running this effect on that change would refetch /tags/ per click and
	// race the optimistic selection.
	useEffect(() => {
		if (!open) return;
		setError(null);
		setSelectedTagId(agent.tag?.id ?? null);
		api
			.get<AgentTag[]>("/tags/")
			.then((res) => {
				setTags(res.data);
			})
			.catch((err: unknown) => {
				setError(getApiErrorMessage(err, "Failed to load tags"));
			});
		// eslint-disable-next-line react-hooks/exhaustive-deps -- agent.tag seeds the selection on open; later changes are driven by assignTag itself
	}, [open, agent.id]);

	const assignTag = async (tagId: string | null) => {
		if (isAssigning || tagId === selectedTagId) return;
		const previous = selectedTagId;
		setSelectedTagId(tagId);
		setIsAssigning(true);
		setError(null);
		try {
			const response = await api.patch(`/agents/${agent.id}`, { tagId });
			updateAgent(agent.id, response.data as Agent);
		} catch (err) {
			setSelectedTagId(previous);
			setError(getApiErrorMessage(err, "Failed to assign the tag"));
		} finally {
			setIsAssigning(false);
		}
	};

	const openCreateTag = () => {
		setEditingTag(null);
		setTagDialogOpen(true);
	};

	const openEditTag = (tag: AgentTag) => {
		setEditingTag(tag);
		setTagDialogOpen(true);
	};

	const handleTagCreated = (tag: AgentTag) => {
		setTags((prev) => [...prev, tag].sort(byName));
	};

	const handleTagUpdated = (updated: AgentTag) => {
		setTags((prev) =>
			prev.map((t) => (t.id === updated.id ? updated : t)).sort(byName),
		);
		// Renaming affects every agent carrying this tag, not just the open one.
		applyTagUpdate({ id: updated.id, name: updated.name });
	};

	const handleDeleteTag = async (tag: AgentTag) => {
		if (
			!window.confirm(
				`Delete the "${tag.name}" tag? Agents with this tag become untagged.`,
			)
		) {
			return;
		}
		setError(null);
		try {
			await api.delete(`/tags/${tag.id}`);
			setTags((prev) => prev.filter((t) => t.id !== tag.id));
			// The backend FK is ON DELETE SET NULL — mirror it for every agent
			// that carried the tag, not just the open one.
			applyTagRemoval(tag.id);
			if (selectedTagId === tag.id) {
				setSelectedTagId(null);
			}
		} catch (err) {
			setError(getApiErrorMessage(err, "Failed to delete the tag"));
		}
	};

	const renderRow = (tag: AgentTag) => {
		const selected = selectedTagId === tag.id;
		return (
			<div
				key={tag.id}
				className="group flex items-center gap-3 border-b border-[#edf2ef] px-[18px] transition-colors duration-[110ms] last:border-b-0 hover:bg-[#eff4f1] dark:border-white/5 dark:hover:bg-white/5"
			>
				<button
					type="button"
					onClick={() => {
						// Clicking the selected tag again clears it (untags the agent).
						void assignTag(selected ? null : tag.id);
					}}
					className="flex flex-1 items-center gap-3 py-[11px] text-left cursor-pointer min-w-0"
				>
					<span className="flex-1 truncate font-[family-name:var(--font-jakarta-sans)] text-[13.5px] font-semibold tracking-[-0.01em] text-[#1e2d28] dark:text-foreground">
						{tag.name}
					</span>
					{selected && (
						<Check className="size-4 shrink-0 text-[#4CA882]" />
					)}
				</button>
				{isWorkspaceAdmin && (
					<SageDropdownMenu
						trigger={
							<button className="flex size-7 items-center justify-center rounded-[7px] text-[#94a59d] cursor-pointer transition-all hover:bg-[#edf2ef] md:opacity-0 md:group-hover:opacity-100 dark:hover:bg-white/10">
								<MoreVertical className="size-[18px]" />
							</button>
						}
						items={[
							{
								label: "Rename",
								icon: <Pencil />,
								onClick: () => {
									openEditTag(tag);
								},
							},
							{
								label: "Delete",
								icon: <Trash2 />,
								destructive: true,
								onClick: () => {
									void handleDeleteTag(tag);
								},
							},
						]}
					/>
				)}
			</div>
		);
	};

	return (
		<>
			<Dialog open={open} onOpenChange={onOpenChange}>
				<DialogContent
					className="sm:max-w-[460px] rounded-[28px] p-0 gap-0 overflow-hidden"
					showCloseButton={false}
				>
					{/* Header */}
					<div className="flex items-start justify-between px-8 pt-7 pb-0">
						<div>
							<DialogTitle className="font-[family-name:var(--font-jakarta-sans)] text-[22px] font-extrabold text-[#111111] dark:text-white tracking-[-0.02em]">
								Assign a tag
							</DialogTitle>
							<p className="font-[family-name:var(--font-dm-sans)] text-[14px] text-[#8FA89E] dark:text-muted-foreground font-medium mt-2 leading-relaxed">
								Choose which section{" "}
								<span className="font-semibold text-[#6B7F76] dark:text-foreground">
									{agent.name}
								</span>{" "}
								appears under in the gallery
							</p>
						</div>
						<button
							type="button"
							aria-label="Close"
							onClick={() => {
								onOpenChange(false);
							}}
							className="shrink-0 flex items-center justify-center w-9 h-9 rounded-full bg-[#F5F8F6] dark:bg-white/10 text-[#6B7F76] hover:bg-[#EDF4F0] dark:hover:bg-white/15 transition-colors cursor-pointer"
						>
							<X className="w-4 h-4" />
						</button>
					</div>

					{/* Content */}
					<div className="px-8 pt-5 pb-7">
						{error && (
							<div className="mb-4 p-3.5 rounded-2xl bg-red-50 dark:bg-red-950/30 text-[13px] font-medium text-red-600 dark:text-red-400 font-[family-name:var(--font-dm-sans)]">
								{error}
							</div>
						)}

						{tags.length === 0 ? (
							<div className="rounded-[14px] border border-dashed border-[#d8e3dd] bg-transparent px-[18px] py-8 text-center text-[14px] font-medium text-[#A3B5AD] dark:border-white/10 dark:text-muted-foreground">
								{isWorkspaceAdmin
									? "No tags yet. Create one to group agents."
									: "No tags yet. Ask a workspace admin to create some."}
							</div>
						) : (
							<div className="max-h-[300px] overflow-y-auto rounded-[14px] border border-[#e1ebe6] bg-white dark:border-white/10 dark:bg-card [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
								{tags.map((tag) => renderRow(tag))}
							</div>
						)}
					</div>

					{/* Footer */}
					{isWorkspaceAdmin && (
						<div className="flex items-center justify-end px-8 pb-6">
							<SageButton color="outline" onClick={openCreateTag}>
								<Plus className="size-3.5" />
								New tag
							</SageButton>
						</div>
					)}
				</DialogContent>
			</Dialog>

			<NewTagDialog
				open={tagDialogOpen}
				onOpenChange={setTagDialogOpen}
				tag={editingTag}
				onTagCreated={handleTagCreated}
				onTagUpdated={handleTagUpdated}
			/>
		</>
	);
}
