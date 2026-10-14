"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import { ChevronDown, Info, Loader2, TriangleAlert } from "lucide-react";
import * as langfuseApi from "@/lib/api/resources/langfuse";
import { getApiErrorMessage } from "@/lib/api/errors";
import { DropdownMenu } from "@/components/ui/dropdown-menu";
import ConfirmDialog from "@/components/ui/confirm-dialog";
import { cn } from "@/lib/utils";
import { relativeTime } from "../../skills/lib/relative-time";

type PromptVersion = langfuseApi.LangfusePromptVersion;

interface AgentLangfusePanelProps {
	agentId: string;
	agentName: string;
	readOnly: boolean;
	/** Publishing and promoting to production are workspace-admin only. */
	isWorkspaceAdmin: boolean;
	/** Edit mode: the version picked into the draft instructions, if any. */
	pickedVersion: number | null;
	/** Edit mode: the draft instructions differ from what was last loaded. */
	hasUnsavedEdits: boolean;
	onPick: (version: PromptVersion) => void;
}

function LabelPill({ label }: { label: string }) {
	return (
		<span
			className={cn(
				"rounded-full px-1.5 py-px text-[11px] font-semibold",
				label === "production"
					? "bg-petrol text-white"
					: "bg-petrol-tint text-petrol dark:bg-white/10 dark:text-panel-body",
			)}
		>
			{label}
		</span>
	);
}

function VersionMeta({ version }: { version: PromptVersion }) {
	const details = [
		version.author,
		version.createdAt && relativeTime(version.createdAt),
	].filter(Boolean);
	return (
		<span className="flex flex-wrap items-center gap-1.5 text-[11.5px] font-normal text-meta dark:text-panel-dim">
			{version.labels.map((label) => (
				<LabelPill key={label} label={label} />
			))}
			{details.join(" · ")}
		</span>
	);
}

function Spinner() {
	return (
		<div className="flex items-center gap-2 py-6 text-[13px] text-meta dark:text-panel-dim">
			<Loader2 className="size-4 animate-spin" />
			Loading versions…
		</div>
	);
}

/**
 * The Versions editor tab, backed by Langfuse's prompt registry. Langfuse
 * serves external consumers; auxilia's saved instructions are what runs here.
 * Read mode shows the production version and releases the saved instructions;
 * edit mode loads a version into the draft (labelled production on save).
 */
export default function AgentLangfusePanel({
	agentId,
	agentName,
	readOnly,
	isWorkspaceAdmin,
	pickedVersion,
	hasUnsavedEdits,
	onPick,
}: AgentLangfusePanelProps) {
	const [prompt, setPrompt] = useState<langfuseApi.LangfusePrompt | null>(null);
	const [versions, setVersions] = useState<PromptVersion[] | null>(null);
	const [commitMessage, setCommitMessage] = useState("");
	const [isPublishing, setIsPublishing] = useState(false);
	const [error, setError] = useState<string | null>(null);
	// A version waiting for "Replace your unsaved edits?" confirmation.
	const [pending, setPending] = useState<PromptVersion | null>(null);

	useEffect(() => {
		setError(null);
		const load = readOnly
			? langfuseApi.getLangfusePrompt(agentId).then(setPrompt)
			: langfuseApi.listLangfuseVersions(agentId).then(setVersions);
		load.catch((err: unknown) => {
			setError(getApiErrorMessage(err, "Failed to reach Langfuse"));
		});
	}, [agentId, readOnly]);

	const publish = async () => {
		setIsPublishing(true);
		setError(null);
		try {
			// The new version is production and was cut from the saved
			// instructions, so it can't diverge: no follow-up fetch to fail.
			const production = await langfuseApi.publishLangfusePrompt(
				agentId,
				commitMessage.trim() || null,
			);
			setCommitMessage("");
			setPrompt({ production, diverged: false });
		} catch (err) {
			setError(getApiErrorMessage(err, "Failed to publish to Langfuse"));
		} finally {
			setIsPublishing(false);
		}
	};

	const errorBox = error && (
		<div className="rounded-md bg-destructive/10 px-4 py-2.5 text-[13px] text-destructive">
			{error}
		</div>
	);

	const publishForm = (placeholder: string) =>
		isWorkspaceAdmin ? (
			<div className="flex gap-2">
				<input
					type="text"
					value={commitMessage}
					onChange={(e) => {
						setCommitMessage(e.target.value);
					}}
					placeholder={placeholder}
					className="min-w-0 flex-1 rounded-lg border border-input bg-card px-3 py-[7px] text-[13px] outline-none transition-[border-color,box-shadow] placeholder:text-meta focus:border-petrol focus:shadow-[0_0_0_3px_rgba(22,96,110,0.10)] dark:placeholder:text-panel-dim"
				/>
				<button
					type="button"
					disabled={isPublishing}
					onClick={() => {
						void publish();
					}}
					className="shrink-0 cursor-pointer rounded-[7px] bg-petrol px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
				>
					{isPublishing ? "Publishing…" : "Publish to Langfuse"}
				</button>
			</div>
		) : (
			<p className="text-[12.5px] text-meta dark:text-panel-dim">
				Only workspace admins can publish to Langfuse.
			</p>
		);

	if (!readOnly) {
		if (!versions) return errorBox || <Spinner />;
		const current =
			versions.find((v) => v.version === pickedVersion) ??
			versions.find((v) => v.labels.includes("production"));
		const pick = (v: PromptVersion) => {
			if (v.version === current?.version && !hasUnsavedEdits) return;
			if (hasUnsavedEdits) setPending(v);
			else onPick(v);
		};
		return (
			<div className="flex flex-col gap-2">
				{errorBox}
				{versions.length === 0 ? (
					<p className="text-[13px] text-meta dark:text-panel-dim">
						No Langfuse versions yet. Save the agent, then publish its
						instructions from this tab.
					</p>
				) : (
					<>
						<span className="flex items-center gap-1.5 text-[12.5px] font-semibold text-foreground">
							<Image
								unoptimized
								src="https://pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev/assets/icons/langfuse.png"
								alt=""
								width={14}
								height={14}
								className="size-3.5 object-contain"
							/>
							Langfuse version
						</span>
						<DropdownMenu
							align="start"
							className="w-[var(--radix-dropdown-menu-trigger-width)]"
							trigger={
								<button
									type="button"
									className="flex w-full cursor-pointer items-center gap-2.5 rounded-[10px] border border-input bg-card px-3 py-2.5 text-left text-[13px] transition-colors hover:border-border-hover data-[state=open]:border-petrol data-[state=open]:shadow-[0_0_0_3px_rgba(22,96,110,0.10)]"
								>
									{current ? (
										<>
											<span className="font-mono font-semibold text-foreground">
												v{current.version}
											</span>
											{current.labels
												.filter((l) => l === "production")
												.map((l) => (
													<LabelPill key={l} label={l} />
												))}
											<span className="min-w-0 flex-1 truncate text-muted-foreground">
												{current.commitMessage}
											</span>
										</>
									) : (
										<span className="flex-1 text-muted-foreground">
											Select a version
										</span>
									)}
									<ChevronDown className="size-3.5 shrink-0 text-meta" />
								</button>
							}
							items={versions.map((v) => ({
								active: v.version === current?.version,
								onClick: () => {
									pick(v);
								},
								label: (
									<span className="flex items-start gap-2.5">
										<span className="w-7 shrink-0 font-mono font-semibold">
											v{v.version}
										</span>
										<span className="flex min-w-0 flex-col gap-1">
											<span className="font-semibold">
												{v.commitMessage || "No commit message"}
											</span>
											<VersionMeta version={v} />
										</span>
									</span>
								),
							}))}
						/>
						{pickedVersion !== null && (
							<div className="mt-1 flex items-start gap-2.5 rounded-[10px] bg-petrol-tint px-4 py-3 text-[13px] text-foreground dark:bg-white/5">
								<Info className="mt-0.5 size-4 shrink-0 text-petrol" />
								<span>
									{isWorkspaceAdmin ? (
										<>
											When you save, <strong>v{pickedVersion}</strong> becomes the
											production version in Langfuse. Anything that fetches this
											prompt from Langfuse will start using it.
										</>
									) : (
										<>
											When you save, <strong>v{pickedVersion}</strong> becomes this
											agent&apos;s instructions. Langfuse production stays as it
											is: only workspace admins can change it.
										</>
									)}
								</span>
							</div>
						)}
					</>
				)}
				<ConfirmDialog
					open={pending !== null}
					onOpenChange={(open) => {
						if (!open) setPending(null);
					}}
					title="Replace your unsaved edits?"
					description={`Loading v${pending?.version ?? ""} will replace the current instructions. Your unsaved changes will be lost.`}
					confirmLabel="Replace"
					onConfirm={() => {
						if (pending) onPick(pending);
					}}
				/>
			</div>
		);
	}

	if (!prompt) return errorBox || <Spinner />;

	if (!prompt.production) {
		return (
			<div className="flex flex-col gap-3 rounded-[10px] border border-dashed border-input px-5 py-6">
				{errorBox}
				<p className="text-[14px] font-semibold text-foreground">
					Manage agent instructions with Langfuse
				</p>
				<p className="text-[13px] text-muted-foreground">
					Publish the saved instructions as a Langfuse prompt labelled
					production. Langfuse keeps the version history; external consumers
					can fetch the prompt from there.
				</p>
				{publishForm(`Publish first version of ${agentName}`)}
			</div>
		);
	}

	const { production } = prompt;
	return (
		<div className="flex flex-col gap-3">
			{errorBox}
			{prompt.diverged && (
				<div className="flex items-start gap-2.5 rounded-[10px] bg-warning-bg px-4 py-3 text-[13px] font-medium text-warning dark:bg-amber-950/30 dark:text-amber-400">
					<TriangleAlert className="mt-0.5 size-4 shrink-0" />
					The Langfuse production prompt and the agent instructions have
					diverged.
				</div>
			)}
			<div className="flex gap-2.5 rounded-[10px] border border-border bg-card px-4 py-3 text-[13px]">
				<span className="w-7 shrink-0 font-mono font-semibold text-foreground">
					v{production.version}
				</span>
				<span className="flex min-w-0 flex-col gap-1">
					<span className="font-semibold text-foreground">
						{production.commitMessage || "No commit message"}
					</span>
					<VersionMeta version={production} />
				</span>
			</div>
			{prompt.diverged && publishForm("Commit message (optional)")}
		</div>
	);
}
