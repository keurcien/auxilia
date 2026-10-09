"use client";

import { useEffect, useState } from "react";
import { Switch } from "@/components/ui/switch";
import { HeaderButton } from "@/components/layout/subpage-header";
import { Input } from "@/components/ui/input";
import * as authApi from "@/lib/api/resources/auth";
import { isApiError } from "@/lib/api/errors";
import type { WorkspaceAuthenticationSettings } from "@/types/auth";

interface Props {
	onForbidden: () => void;
}

const labelClass =
	"mb-1.5 block text-[12px] font-semibold text-subtle dark:text-panel-body";

export default function WorkspaceAuthentication({ onForbidden }: Props) {
	const [settings, setSettings] =
		useState<WorkspaceAuthenticationSettings | null>(null);
	const [enabled, setEnabled] = useState(false);
	const [exclusive, setExclusive] = useState(false);
	const [clientId, setClientId] = useState("");
	const [clientSecret, setClientSecret] = useState("");
	const [saving, setSaving] = useState(false);
	const [status, setStatus] = useState<string | null>(null);

	useEffect(() => {
		void authApi
			.getWorkspaceAuthentication()
			.then((value) => {
				setSettings(value);
				setEnabled(value.enabled);
				setExclusive(value.googleExclusive);
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
			const replacing = clientId.trim() || clientSecret.trim();
			const updated = await authApi.updateWorkspaceAuthentication({
				enabled,
				googleExclusive: exclusive,
				...(replacing
					? {
							clientId: clientId.trim(),
							clientSecret: clientSecret.trim(),
						}
					: {}),
			});
			setSettings(updated);
			setClientId("");
			setClientSecret("");
			setStatus("Authentication settings saved.");
		} catch (error: unknown) {
			if (isApiError(error) && error.status === 403) onForbidden();
			setStatus(
				isApiError(error) && error.detail
					? error.detail
					: "Could not save authentication settings.",
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
			const updated = await authApi.updateWorkspaceAuthentication({
				enabled: checked,
				googleExclusive: checked && exclusive,
			});
			setSettings(updated);
			setExclusive(updated.googleExclusive);
			setStatus(
				checked ? "Google authentication enabled." : "Google authentication disabled.",
			);
		} catch (error: unknown) {
			setEnabled(!checked);
			if (isApiError(error) && error.status === 403) onForbidden();
			setStatus(
				isApiError(error) && error.detail
					? error.detail
					: "Could not update authentication settings.",
			);
		} finally {
			setSaving(false);
		}
	};

	return (
		<div>
			<div className="mb-1.5 flex items-baseline gap-2.5">
				<span className="text-[10.5px] font-semibold text-subtle dark:text-panel-dim">
					Authentication
				</span>
				<span className="text-[10.5px] text-meta dark:text-panel-dim">admin</span>
			</div>
			<p className="mb-3.5 max-w-[620px] text-[13px] leading-[1.55] text-subtle dark:text-panel-body">
				Configure Google sign-in for this workspace. Credentials are encrypted
				before they are stored.
			</p>
			<div className="overflow-hidden rounded-[10px] border border-border bg-card dark:border-white/10">
				<div className="space-y-5 px-4 py-4">
					<div className="flex items-center justify-between gap-4">
						<div>
							<div className="text-[13px] font-semibold text-foreground">
								Google OAuth
							</div>
							<div className="text-[11.5px] text-meta">
								{settings.isConfigured
									? `Configured, client ID ending in ${settings.clientIdLast4}`
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
								<span className={labelClass}>Client ID</span>
								<Input
									value={clientId}
									onChange={(event) => {
										setClientId(event.target.value);
									}}
									placeholder={
										settings.isConfigured
											? "Leave blank to keep current"
											: ""
									}
								/>
							</label>
							<label className="block">
								<span className={labelClass}>Client secret</span>
								<Input
									type="password"
									value={clientSecret}
									onChange={(event) => {
										setClientSecret(event.target.value);
									}}
									placeholder={
										settings.isConfigured
											? "Leave blank to keep current"
											: ""
									}
								/>
							</label>
							<label className="block">
								<span className={labelClass}>Authorized redirect URI</span>
								<Input
									readOnly
									value={settings.callbackUrl}
									className="font-mono"
								/>
							</label>
							<div className="flex items-center justify-between gap-4 border-t border-hairline pt-4">
								<div>
									<div className="text-[13px] font-semibold text-foreground">
										Google-only authentication
									</div>
									<div className="text-[11.5px] text-meta">
										Disable password sign-in and invite acceptance.
									</div>
								</div>
								<Switch
									checked={exclusive}
									onCheckedChange={setExclusive}
									className="cursor-pointer data-[state=checked]:bg-petrol"
								/>
							</div>
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
