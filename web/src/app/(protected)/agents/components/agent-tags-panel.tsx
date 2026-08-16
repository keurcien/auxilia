"use client";

import { useEffect, useState } from "react";
import { Check, MoreVertical, Pencil, Plus, Trash2 } from "lucide-react";
import { api } from "@/lib/api/client";
import { getApiErrorMessage } from "@/lib/api/errors";
import { DropdownMenu } from "@/components/ui/dropdown-menu";
import { useAgentsStore } from "@/stores/agents-store";
import { useUserStore } from "@/stores/user-store";
import { Agent, AgentTag } from "@/types/agents";
import NewTagDialog from "./new-tag-dialog";

interface AgentTagsPanelProps {
	agent: Agent;
	/** Viewer can assign a tag to this agent (editors and up). */
	canAssign: boolean;
}

const byName = (a: AgentTag, b: AgentTag) => a.name.localeCompare(b.name);

/**
 * The Tags editor tab: pick which gallery section the agent appears under.
 * Assigning is immediate (own PATCH — not part of the config draft); managing
 * the shared tag vocabulary is workspace-admin only.
 */
export default function AgentTagsPanel({ agent, canAssign }: AgentTagsPanelProps) {
	const updateAgent = useAgentsStore((state) => state.updateAgent);
	const applyTagUpdate = useAgentsStore((state) => state.applyTagUpdate);
	const applyTagRemoval = useAgentsStore((state) => state.applyTagRemoval);
	const user = useUserStore((state) => state.user);
	const isWorkspaceAdmin = user?.role === "admin";

	const [tags, setTags] = useState<AgentTag[]>([]);
	const [selectedTagId, setSelectedTagId] = useState<string | null>(
		agent.tag?.id ?? null,
	);
	const [isAssigning, setIsAssigning] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [tagDialogOpen, setTagDialogOpen] = useState(false);
	const [editingTag, setEditingTag] = useState<AgentTag | null>(null);

	// Fetch once on mount — assigning updates the store, and refetching on
	// that change would race the optimistic selection.
	useEffect(() => {
		setError(null);
		api
			.get<AgentTag[]>("/tags/")
			.then((res) => {
				setTags(res.data);
			})
			.catch((err: unknown) => {
				setError(getApiErrorMessage(err, "Failed to load tags"));
			});
	}, [agent.id]);

	const assignTag = async (tagId: string | null) => {
		if (!canAssign || isAssigning || tagId === selectedTagId) return;
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

	return (
		<div className="flex flex-col gap-4">
			<div className="flex items-center justify-between">
				<p className="text-[13px] text-muted-foreground">
					Choose which section this agent appears under in the gallery.
					{canAssign && " Click the selected tag again to clear it."}
				</p>
				{isWorkspaceAdmin && (
					<button
						className="flex shrink-0 cursor-pointer items-center gap-1 text-[12.5px] font-semibold text-petrol transition-opacity hover:opacity-80"
						onClick={openCreateTag}
					>
						<Plus className="size-3" />
						New tag
					</button>
				)}
			</div>

			{error && (
				<div className="rounded-md bg-destructive/10 px-3.5 py-2.5 text-[13px] text-destructive">
					{error}
				</div>
			)}

			{tags.length === 0 ? (
				<div className="rounded-[10px] border border-dashed border-input px-4 py-8 text-center text-[13px] text-meta dark:text-panel-dim">
					{isWorkspaceAdmin
						? "No tags yet. Create one to group agents."
						: "No tags yet. Ask a workspace admin to create some."}
				</div>
			) : (
				<div className="overflow-hidden rounded-[10px] border border-border bg-card">
					{tags.map((tag) => {
						const selected = selectedTagId === tag.id;
						return (
							<div
								key={tag.id}
								className="group flex items-center gap-3 border-b border-hover px-4 transition-colors last:border-b-0 hover:bg-sidebar dark:border-white/5"
							>
								<button
									type="button"
									disabled={!canAssign}
									onClick={() => {
										// Clicking the selected tag again clears it.
										void assignTag(selected ? null : tag.id);
									}}
									className="flex min-w-0 flex-1 cursor-pointer items-center gap-3 py-2.5 text-left disabled:cursor-default"
								>
									<span className="flex-1 truncate text-[13.5px] font-semibold text-foreground">
										{tag.name}
									</span>
									{selected && (
										<Check className="size-4 shrink-0 text-petrol" />
									)}
								</button>
								{isWorkspaceAdmin && (
									<DropdownMenu
										trigger={
											<button className="flex size-7 cursor-pointer items-center justify-center rounded-[7px] text-meta transition-all hover:bg-hover md:opacity-0 md:group-hover:opacity-100 dark:text-panel-dim dark:hover:bg-white/10">
												<MoreVertical className="size-4" />
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
					})}
				</div>
			)}

			<NewTagDialog
				open={tagDialogOpen}
				onOpenChange={setTagDialogOpen}
				tag={editingTag}
				onTagCreated={handleTagCreated}
				onTagUpdated={handleTagUpdated}
			/>
		</div>
	);
}
