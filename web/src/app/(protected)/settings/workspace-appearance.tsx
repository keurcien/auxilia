"use client";

import { useState } from "react";
import { ImageUpload, ImageFilePreview } from "@/components/ui/image-upload";
import { Input } from "@/components/ui/input";
import { HeaderButton } from "@/components/layout/subpage-header";
import * as appearanceApi from "@/lib/api/resources/appearance";
import { isApiError } from "@/lib/api/errors";
import { useAppearanceStore } from "@/stores/appearance-store";
import type { InstanceAppearance } from "@/types/appearance";

interface InstanceAppearanceProps {
	onForbidden: () => void;
}

function AppearanceForm({
	appearance,
	onForbidden,
}: InstanceAppearanceProps & { appearance: InstanceAppearance }) {
	const setAppearance = useAppearanceStore((state) => state.setAppearance);
	const [appName, setAppName] = useState(appearance.appName);
	const [logoFile, setLogoFile] = useState<File | null>(null);
	const [logoRemoved, setLogoRemoved] = useState(false);
	const [isSaving, setIsSaving] = useState(false);
	const [status, setStatus] = useState<{
		kind: "success" | "error";
		text: string;
	} | null>(null);

	const currentLogoUrl = appearance.logoRevision
		? appearanceApi.appearanceLogoUrl(appearance.logoRevision)
		: null;
	const canSave =
		appName.trim().length > 0 &&
		(appName.trim() !== appearance.appName ||
			logoFile !== null ||
			(logoRemoved && appearance.logoRevision !== null));

	const handleSave = async () => {
		setIsSaving(true);
		setStatus(null);
		try {
			let updated = appearance;
			if (appName.trim() !== appearance.appName) {
				updated = await appearanceApi.updateAppearance(appName.trim());
				setAppearance(updated);
			}
			if (logoFile) {
				updated = await appearanceApi.uploadLogo(logoFile);
				setAppearance(updated);
			} else if (logoRemoved && appearance.logoRevision) {
				updated = await appearanceApi.deleteLogo();
				setAppearance(updated);
			}
			setAppName(updated.appName);
			setLogoFile(null);
			setLogoRemoved(false);
			setStatus({ kind: "success", text: "Appearance saved." });
		} catch (error: unknown) {
			if (isApiError(error) && error.status === 403) {
				onForbidden();
			} else {
				setStatus({
					kind: "error",
					text:
						isApiError(error) && error.detail
							? error.detail
							: "Could not save the instance appearance.",
				});
			}
		} finally {
			setIsSaving(false);
		}
	};

	return (
		<div>
			<div className="mb-1.5 flex items-baseline gap-2.5">
				<span className="text-[10.5px] font-semibold text-subtle dark:text-panel-dim">
					Instance appearance
				</span>
				<span className="text-[10.5px] text-meta dark:text-panel-dim">
					admin
				</span>
			</div>
			<p className="mb-3.5 max-w-[620px] text-[13px] leading-[1.55] text-subtle dark:text-panel-body">
				Customize the name and logo used throughout this instance.
			</p>

			<div className="overflow-hidden rounded-[10px] border border-border bg-card dark:border-white/10">
				<div className="border-b border-hairline bg-sidebar px-4 py-3 dark:border-white/5 dark:bg-white/[0.03]">
					<span className="text-[12px] font-semibold text-subtle dark:text-panel-body">
						Preview
					</span>
					<div className="mt-3 flex h-14 items-center gap-3 rounded-[9px] border border-border bg-background px-3.5 dark:border-white/10">
						<div className="flex size-8 shrink-0 items-center justify-center overflow-hidden rounded-[7px] bg-petrol">
							{logoFile ? (
								<ImageFilePreview file={logoFile} />
							) : currentLogoUrl && !logoRemoved ? (
								// eslint-disable-next-line @next/next/no-img-element
								<img
									src={currentLogoUrl}
									alt=""
									className="size-full object-cover"
								/>
							) : (
								// eslint-disable-next-line @next/next/no-img-element
								<img src="/logo-dark.svg" alt="" className="size-5" />
							)}
						</div>
						<span className="truncate font-display text-[16px] font-bold tracking-[-0.02em] text-foreground">
							{appName.trim() || "Application name"}
						</span>
					</div>
				</div>

				<div className="space-y-5 px-4 py-4">
					<label className="block">
						<span className="mb-1.5 block text-[12px] font-semibold text-subtle dark:text-panel-body">
							Application name
						</span>
						<Input
							value={appName}
							maxLength={50}
							disabled={isSaving}
							onChange={(event) => {
								setAppName(event.target.value);
							}}
							placeholder="Application name"
							className="max-w-[420px]"
						/>
						<span className="mt-1.5 block text-[11.5px] text-meta dark:text-panel-dim">
							Used for the page title and the brand in the sidebar.
						</span>
					</label>

					<ImageUpload
						currentUrl={currentLogoUrl}
						file={logoFile}
						removed={logoRemoved}
						disabled={isSaving}
						label="Application logo"
						onFileChange={(file) => {
							setLogoFile(file);
							setLogoRemoved(false);
						}}
						onRemove={() => {
							setLogoFile(null);
							setLogoRemoved(true);
						}}
					/>
				</div>

				<div className="flex items-center gap-3 border-t border-hairline px-4 py-3 dark:border-white/5">
					<HeaderButton
						accent
						disabled={!canSave || isSaving}
						onClick={() => {
							void handleSave();
						}}
					>
						{isSaving ? "Saving…" : "Save changes"}
					</HeaderButton>
					{status && (
						<span
							className={`text-[12px] font-medium ${
								status.kind === "error"
									? "text-destructive"
									: "text-success"
							}`}
						>
							{status.text}
						</span>
					)}
				</div>
			</div>
		</div>
	);
}

export default function InstanceAppearanceSettings({
	onForbidden,
}: InstanceAppearanceProps) {
	const appearance = useAppearanceStore((state) => state.appearance);
	const isInitialized = useAppearanceStore((state) => state.isInitialized);

	if (!isInitialized) {
		return (
			<div className="h-64 animate-pulse rounded-[10px] border border-border bg-card" />
		);
	}

	return (
		<AppearanceForm
			appearance={appearance}
			onForbidden={onForbidden}
		/>
	);
}
