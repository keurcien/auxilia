"use client";

import { useEffect, useState } from "react";
import { ChevronDown } from "lucide-react";
import * as langfuseApi from "@/lib/api/resources/langfuse";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
	Dialog,
	DialogButton,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { DropdownMenu } from "@/components/ui/dropdown-menu";
import { Textarea } from "@/components/ui/textarea";

const PRODUCTION = "production";

interface LangfusePublishDialogProps {
	agentId: string;
	open: boolean;
	onOpenChange: (open: boolean) => void;
	/** Default commit message, shown as the input's placeholder. */
	messagePlaceholder: string;
	/** Langfuse has the new version; the caller refetches. */
	onPublished: () => void;
}

/**
 * Review step before a publish: the commit message, the label the new version
 * gets (the prompt's existing labels, production by default) and the config
 * Langfuse stores with it, pre-filled from the agent's MCP bindings.
 */
export default function LangfusePublishDialog({
	agentId,
	open,
	onOpenChange,
	messagePlaceholder,
	onPublished,
}: LangfusePublishDialogProps) {
	const [labels, setLabels] = useState<string[] | null>(null);
	const [commitMessage, setCommitMessage] = useState("");
	const [label, setLabel] = useState(PRODUCTION);
	const [configJson, setConfigJson] = useState("");
	const [isPublishing, setIsPublishing] = useState(false);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		if (!open) return;
		setLabels(null);
		setError(null);
		setCommitMessage("");
		setLabel(PRODUCTION);
		let stale = false;
		langfuseApi
			.getLangfusePublishDraft(agentId)
			.then((draft) => {
				if (stale) return;
				setLabels(draft.labels);
				setConfigJson(draft.configJson);
			})
			.catch((err: unknown) => {
				if (stale) return;
				setError(getApiErrorMessage(err, "Failed to reach Langfuse"));
			});
		return () => {
			stale = true;
		};
	}, [open, agentId]);

	const publish = async () => {
		setIsPublishing(true);
		setError(null);
		try {
			await langfuseApi.publishLangfusePrompt(agentId, {
				commitMessage: commitMessage.trim() || null,
				label,
				configJson,
			});
			onPublished();
			onOpenChange(false);
		} catch (err) {
			setError(getApiErrorMessage(err, "Failed to publish to Langfuse"));
		} finally {
			setIsPublishing(false);
		}
	};

	const fieldLabel = "text-[12.5px] font-semibold text-foreground";
	const control =
		"w-full rounded-lg border border-input bg-card px-3 py-[7px] text-[13px] outline-none transition-[border-color,box-shadow] placeholder:text-meta focus:border-petrol focus:shadow-[0_0_0_3px_rgba(22,96,110,0.10)] dark:placeholder:text-panel-dim";

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="sm:max-w-[640px]">
				<DialogHeader>
					<DialogTitle>Publish to Langfuse</DialogTitle>
					<DialogDescription>
						Releases the saved instructions as a new version of this
						agent&apos;s prompt, with the config below, under the label you
						pick.
					</DialogDescription>
				</DialogHeader>
				{error && (
					<div className="rounded-md bg-destructive/10 px-4 py-2.5 text-[13px] text-destructive">
						{error}
					</div>
				)}
				<label className="flex flex-col gap-1.5">
					<span className={fieldLabel}>Commit message</span>
					<input
						type="text"
						value={commitMessage}
						onChange={(e) => {
							setCommitMessage(e.target.value);
						}}
						placeholder={messagePlaceholder}
						className={control}
					/>
				</label>
				<div className="flex flex-col gap-1.5">
					<span className={fieldLabel}>Label</span>
					<DropdownMenu
						align="start"
						className="w-[var(--radix-dropdown-menu-trigger-width)]"
						trigger={
							<button
								type="button"
								aria-label="Langfuse label"
								disabled={!labels}
								className={`${control} flex cursor-pointer items-center gap-2 text-left disabled:cursor-not-allowed disabled:opacity-50`}
							>
								<span className="flex-1">{label}</span>
								<ChevronDown className="size-3.5 shrink-0 text-meta" />
							</button>
						}
						items={(labels ?? [PRODUCTION]).map((l) => ({
							label: l,
							active: l === label,
							onClick: () => {
								setLabel(l);
							},
						}))}
					/>
				</div>
				<label className="flex flex-col gap-1.5">
					<span className={fieldLabel}>Config</span>
					<Textarea
						value={configJson}
						disabled={!labels}
						spellCheck={false}
						onChange={(e) => {
							setConfigJson(e.target.value);
						}}
						className={`${control} max-h-72 min-h-40 overflow-auto font-mono text-[12px] md:text-[12px]`}
					/>
				</label>
				<DialogFooter>
					<DialogButton
						variant="outline"
						onClick={() => {
							onOpenChange(false);
						}}
					>
						Cancel
					</DialogButton>
					<DialogButton
						disabled={!labels || isPublishing}
						onClick={() => {
							void publish();
						}}
					>
						{isPublishing ? "Publishing…" : "Publish"}
					</DialogButton>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}
