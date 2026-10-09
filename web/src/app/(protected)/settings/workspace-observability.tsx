"use client";

import { useEffect, useState } from "react";
import { HeaderButton } from "@/components/layout/subpage-header";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { isApiError } from "@/lib/api/errors";
import * as observabilityApi from "@/lib/api/resources/observability";
import type { WorkspaceObservabilitySettings } from "@/types/observability";

interface Props {
	onForbidden: () => void;
}

const labelClass =
	"mb-1.5 block text-[12px] font-semibold text-subtle dark:text-panel-body";

export default function WorkspaceObservability({ onForbidden }: Props) {
	const [settings, setSettings] =
		useState<WorkspaceObservabilitySettings | null>(null);
	const [enabled, setEnabled] = useState(false);
	const [baseUrl, setBaseUrl] = useState("");
	const [timeout, setTimeoutValue] = useState(15);
	const [publicKey, setPublicKey] = useState("");
	const [secretKey, setSecretKey] = useState("");
	const [saving, setSaving] = useState(false);
	const [status, setStatus] = useState<string | null>(null);

	useEffect(() => {
		void observabilityApi
			.getObservabilitySettings()
			.then((value) => {
				setSettings(value);
				setEnabled(value.enabled);
				setBaseUrl(value.baseUrl);
				setTimeoutValue(value.timeoutSeconds);
			})
			.catch((error: unknown) => {
				if (isApiError(error) && error.status === 403) onForbidden();
			});
	}, [onForbidden]);

	if (!settings) {
		return (
			<div className="h-64 animate-pulse rounded-[10px] border border-border bg-card" />
		);
	}

	const save = async () => {
		setSaving(true);
		setStatus(null);
		try {
			const replacing = publicKey.trim() || secretKey.trim();
			const updated = await observabilityApi.updateObservabilitySettings({
				enabled,
				baseUrl: baseUrl.trim(),
				timeoutSeconds: timeout,
				...(replacing
					? {
							publicKey: publicKey.trim(),
							secretKey: secretKey.trim(),
						}
					: {}),
			});
			setSettings(updated);
			setPublicKey("");
			setSecretKey("");
			setStatus("Observability settings saved.");
		} catch (error: unknown) {
			if (isApiError(error) && error.status === 403) onForbidden();
			setStatus(
				isApiError(error) && error.detail
					? error.detail
					: "Could not save observability settings.",
			);
		} finally {
			setSaving(false);
		}
	};

	const toggleEnabled = async (checked: boolean) => {
		setEnabled(checked);
		setStatus(null);
		if (checked && !settings.isConfigured) return;

		setSaving(true);
		try {
			const updated = await observabilityApi.updateObservabilitySettings({
				enabled: checked,
				baseUrl: baseUrl.trim(),
				timeoutSeconds: timeout,
			});
			setSettings(updated);
			setStatus(
				checked ? "Observability enabled." : "Observability disabled.",
			);
		} catch (error: unknown) {
			setEnabled(!checked);
			if (isApiError(error) && error.status === 403) onForbidden();
			setStatus(
				isApiError(error) && error.detail
					? error.detail
					: "Could not update observability settings.",
			);
		} finally {
			setSaving(false);
		}
	};

	return (
		<div>
			<div className="mb-1.5 flex items-baseline gap-2.5">
				<span className="text-[10.5px] font-semibold text-subtle dark:text-panel-dim">
					Observability
				</span>
				<span className="text-[10.5px] text-meta dark:text-panel-dim">admin</span>
			</div>
			<p className="mb-3.5 max-w-[620px] text-[13px] leading-[1.55] text-subtle dark:text-panel-body">
				Send agent traces, costs and generations to Langfuse.
			</p>
			<div className="overflow-hidden rounded-[10px] border border-border bg-card dark:border-white/10">
				<div className="space-y-5 px-4 py-4">
					<div className="flex items-center justify-between gap-4">
						<div>
							<div className="text-[13px] font-semibold text-foreground">
								Langfuse
							</div>
							<div className="text-[11.5px] text-meta">
								{settings.isConfigured
									? `Configured, public key ending in ${settings.publicKeyLast4}`
									: "Not configured"}
							</div>
						</div>
						<Switch
							checked={enabled}
							disabled={saving}
							onCheckedChange={(checked) => {
								void toggleEnabled(checked);
							}}
							className="cursor-pointer data-[state=checked]:bg-petrol"
						/>
					</div>
					{enabled && (
						<>
							<label className="block">
								<span className={labelClass}>Base URL</span>
								<Input
									type="url"
									value={baseUrl}
									onChange={(event) => {
										setBaseUrl(event.target.value);
									}}
								/>
							</label>
							<div className="grid gap-4 sm:grid-cols-2">
								<label className="block">
									<span className={labelClass}>Public key</span>
									<Input
										type="password"
										value={publicKey}
										onChange={(event) => {
											setPublicKey(event.target.value);
										}}
										placeholder={
											settings.isConfigured
												? "Leave blank to keep current"
												: ""
										}
									/>
								</label>
								<label className="block">
									<span className={labelClass}>Secret key</span>
									<Input
										type="password"
										value={secretKey}
										onChange={(event) => {
											setSecretKey(event.target.value);
										}}
										placeholder={
											settings.isConfigured
												? "Leave blank to keep current"
												: ""
										}
									/>
								</label>
							</div>
							<label className="block max-w-[180px]">
								<span className={labelClass}>Timeout in seconds</span>
								<Input
									type="number"
									min={1}
									max={120}
									value={timeout}
									onChange={(event) => {
										setTimeoutValue(Number(event.target.value));
									}}
								/>
							</label>
						</>
					)}
				</div>
				{enabled && (
					<div className="flex items-center gap-3 border-t border-hairline px-4 py-3">
						<HeaderButton
							accent
							disabled={saving}
							onClick={() => {
								void save();
							}}
						>
							{saving ? "Saving…" : "Save changes"}
						</HeaderButton>
						{status && (
							<span className="text-[12px] text-subtle">{status}</span>
						)}
					</div>
				)}
			</div>
		</div>
	);
}
