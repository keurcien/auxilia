"use client";

import { useEffect, useState } from "react";
import { Images } from "lucide-react";
import * as mcpServersApi from "@/lib/api/resources/mcp-servers";
import { getApiErrorMessage } from "@/lib/api/errors";
import { useConfirmDialog } from "@/components/providers/dialog-provider";
import type { ImagePreviewSettings } from "@/types/mcp-servers";

const INPUT_CLASS =
	"w-full rounded-lg border border-input bg-card px-3 py-[9px] font-mono text-[12.5px] text-foreground outline-none transition-[border-color,box-shadow] placeholder:text-meta dark:placeholder:text-panel-dim focus:border-petrol focus:shadow-[0_0_0_3px_rgba(22,96,110,0.10)]";

/**
 * Admin settings that let the chat gallery show images this server only
 * references by id: the image URL with an {id} placeholder, plus an optional
 * secret header (an API key) the backend adds to that request.
 */
export function ImagePreviewsPanel({ serverId }: { serverId: string }) {
	const confirmDialog = useConfirmDialog();
	const [saved, setSaved] = useState<ImagePreviewSettings | null>(null);
	const [urlTemplate, setUrlTemplate] = useState("");
	const [headerName, setHeaderName] = useState("");
	const [headerValue, setHeaderValue] = useState("");
	const [isLoading, setIsLoading] = useState(true);
	const [isSaving, setIsSaving] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [notice, setNotice] = useState<string | null>(null);

	useEffect(() => {
		let active = true;
		void mcpServersApi
			.getMcpServerImagePreviews(serverId)
			.then((settings) => {
				if (!active) return;
				setSaved(settings);
				setUrlTemplate(settings?.urlTemplate ?? "");
				setHeaderName(settings?.headerName ?? "");
			})
			.catch((err: unknown) => {
				if (active) setError(getApiErrorMessage(err, "Failed to load settings."));
			})
			.finally(() => {
				if (active) setIsLoading(false);
			});
		return () => {
			active = false;
		};
	}, [serverId]);

	const name = headerName.trim();
	const keepsValue =
		saved !== null && saved.headerValueSet && saved.headerName === name;
	const needsValue = name.length > 0 && !keepsValue && !headerValue;
	const canSave = urlTemplate.includes("{id}") && !needsValue && !isSaving;

	const handleSave = async () => {
		setIsSaving(true);
		setError(null);
		setNotice(null);
		try {
			const next = await mcpServersApi.saveMcpServerImagePreviews(serverId, {
				urlTemplate: urlTemplate.trim(),
				headerName: name || null,
				...(headerValue ? { headerValue } : {}),
			});
			setSaved(next);
			setHeaderValue("");
			setNotice("Saved. New conversations can show these images.");
		} catch (err) {
			setError(getApiErrorMessage(err, "Failed to save settings."));
		} finally {
			setIsSaving(false);
		}
	};

	const handleRemove = async () => {
		if (
			!(await confirmDialog({
				title: "Turn off image previews?",
				description:
					"Agents will no longer be able to show this server's images in the chat. The stored header value is deleted.",
				confirmLabel: "Turn off",
				destructive: true,
			}))
		)
			return;
		setIsSaving(true);
		setError(null);
		setNotice(null);
		try {
			await mcpServersApi.deleteMcpServerImagePreviews(serverId);
			setSaved(null);
			setUrlTemplate("");
			setHeaderName("");
			setHeaderValue("");
		} catch (err) {
			setError(getApiErrorMessage(err, "Failed to turn off image previews."));
		} finally {
			setIsSaving(false);
		}
	};

	if (isLoading) {
		return (
			<div className="rounded-[10px] border border-border bg-card px-4 py-8 text-center text-[13px] font-medium text-meta dark:text-panel-dim">
				Loading…
			</div>
		);
	}

	return (
		<form
			className="flex flex-col gap-4 rounded-[10px] border border-border bg-card p-[18px]"
			onSubmit={(event) => {
				event.preventDefault();
				if (canSave) void handleSave();
			}}
		>
			<div className="flex items-start gap-3.5">
				<span className="flex size-[34px] shrink-0 items-center justify-center rounded-[9px] bg-petrol-tint text-petrol dark:bg-white/10 dark:text-panel-terminal">
					<Images className="size-4" />
				</span>
				<div className="min-w-0">
					<div className="text-[13.5px] font-semibold text-foreground">
						Image previews in the chat
					</div>
					<div className="mt-1 text-[12.5px] leading-[1.55] text-subtle dark:text-panel-body">
						For servers whose tools return image ids (photos, files) without
						the images themselves. Agents pass an id, the backend downloads
						the image from this URL and shows it in the chat. The header value
						is encrypted and never reaches the browser or the model.
					</div>
				</div>
			</div>

			<label className="flex flex-col gap-[7px]">
				<span className="text-[13px] font-semibold text-foreground">
					Image URL
				</span>
				<input
					type="text"
					autoComplete="off"
					placeholder="https://photos.example.com/api/assets/{id}/thumbnail?size=preview"
					value={urlTemplate}
					onChange={(event) => {
						setUrlTemplate(event.target.value);
						setNotice(null);
					}}
					className={INPUT_CLASS}
				/>
				<span className="text-[11.5px] text-meta dark:text-panel-dim">
					{"{id}"} is replaced by the id the agent got from this server.
				</span>
			</label>

			<div className="grid gap-3 sm:grid-cols-2">
				<label className="flex flex-col gap-[7px]">
					<span className="text-[13px] font-semibold text-foreground">
						Header name (optional)
					</span>
					<input
						type="text"
						autoComplete="off"
						placeholder="x-api-key"
						value={headerName}
						onChange={(event) => {
							setHeaderName(event.target.value);
							setNotice(null);
						}}
						className={INPUT_CLASS}
					/>
				</label>
				<label className="flex flex-col gap-[7px]">
					<span className="text-[13px] font-semibold text-foreground">
						Header value
					</span>
					<input
						type="password"
						autoComplete="off"
						disabled={!name}
						placeholder={keepsValue ? "Saved, leave empty to keep" : "Secret value"}
						value={headerValue}
						onChange={(event) => {
							setHeaderValue(event.target.value);
							setNotice(null);
						}}
						className={`${INPUT_CLASS} disabled:opacity-50`}
					/>
				</label>
			</div>

			{error && (
				<p
					className="rounded-[8px] bg-destructive/10 px-3 py-2.5 text-[12px] leading-[1.5] text-destructive"
					aria-live="polite"
				>
					{error}
				</p>
			)}
			{notice && (
				<p className="text-[12px] text-success" aria-live="polite">
					{notice}
				</p>
			)}

			<div className="flex items-center justify-end gap-2">
				{saved && (
					<button
						type="button"
						disabled={isSaving}
						onClick={() => {
							void handleRemove();
						}}
						className="cursor-pointer rounded-[7px] border border-border px-3 py-[6px] text-[12px] font-semibold text-[#B04A3A] transition-colors hover:bg-[#FBEFED] disabled:cursor-default disabled:opacity-50 dark:hover:bg-rose-950"
					>
						Turn off
					</button>
				)}
				<button
					type="submit"
					disabled={!canSave}
					className="cursor-pointer rounded-[7px] bg-petrol px-3 py-[6px] text-[12px] font-semibold text-white transition-colors hover:bg-petrol/90 disabled:cursor-default disabled:opacity-50"
				>
					{isSaving ? "Saving…" : "Save"}
				</button>
			</div>
		</form>
	);
}
