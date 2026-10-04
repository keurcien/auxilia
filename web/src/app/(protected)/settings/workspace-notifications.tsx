"use client";

import { useCallback, useEffect, useState } from "react";
import { HeaderButton } from "@/components/layout/subpage-header";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { getApiErrorMessage, isApiError } from "@/lib/api/errors";
import * as notificationsApi from "@/lib/api/resources/notifications";
import type { SlackNotificationSettings } from "@/types/notifications";

interface Props {
	onForbidden: () => void;
}

const labelClass =
	"mb-1.5 block text-[12px] font-semibold text-subtle dark:text-panel-body";

export default function WorkspaceNotifications({ onForbidden }: Props) {
	const [settings, setSettings] = useState<SlackNotificationSettings | null>(null);
	const [enabled, setEnabled] = useState(false);
	const [botToken, setBotToken] = useState("");
	const [signingSecret, setSigningSecret] = useState("");
	const [saving, setSaving] = useState(false);
	const [status, setStatus] = useState<string | null>(null);
	const [loadError, setLoadError] = useState<string | null>(null);

	const load = useCallback(async () => {
		setLoadError(null);
		try {
			const value = await notificationsApi.getSlackSettings();
			setSettings(value);
			setEnabled(value.enabled);
		} catch (error: unknown) {
			if (isApiError(error) && error.status === 403) {
				onForbidden();
				return;
			}
			setLoadError(
				getApiErrorMessage(error, "Could not load notification settings."),
			);
		}
	}, [onForbidden]);

	useEffect(() => {
		const timeoutId = window.setTimeout(() => {
			void load();
		}, 0);
		return () => {
			window.clearTimeout(timeoutId);
		};
	}, [load]);

	if (!settings) {
		if (loadError) {
			return (
				<div className="rounded-[10px] border border-destructive/25 bg-destructive/5 p-5">
					<p className="text-[13px] text-destructive">{loadError}</p>
					<button
						type="button"
						onClick={() => {
							void load();
						}}
						className="mt-3 cursor-pointer rounded-[7px] border border-input bg-card px-3 py-1.5 text-[12px] font-semibold text-foreground"
					>
						Retry
					</button>
				</div>
			);
		}
		return (
			<div className="h-64 animate-pulse rounded-[10px] border border-border bg-card" />
		);
	}

	const save = async () => {
		setSaving(true);
		setStatus(null);
		try {
			const replacing = botToken.trim() || signingSecret.trim();
			const updated = await notificationsApi.updateSlackSettings({
				enabled,
				...(replacing
					? {
							botToken: botToken.trim(),
							signingSecret: signingSecret.trim(),
						}
					: {}),
			});
			setSettings(updated);
			setBotToken("");
			setSigningSecret("");
			setStatus("Notification settings saved.");
		} catch (error: unknown) {
			if (isApiError(error) && error.status === 403) onForbidden();
			setStatus(
				isApiError(error) && error.detail
					? error.detail
					: "Could not save notification settings.",
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
			const updated = await notificationsApi.updateSlackSettings({
				enabled: checked,
			});
			setSettings(updated);
			setStatus(
				checked ? "Slack notifications enabled." : "Slack notifications disabled.",
			);
		} catch (error: unknown) {
			setEnabled(!checked);
			if (isApiError(error) && error.status === 403) onForbidden();
			setStatus(
				isApiError(error) && error.detail
					? error.detail
					: "Could not update notification settings.",
			);
		} finally {
			setSaving(false);
		}
	};

	return (
		<div>
			<div className="mb-1.5 flex items-baseline gap-2.5">
				<span className="text-[10.5px] font-semibold text-subtle dark:text-panel-dim">
					Notifications
				</span>
				<span className="text-[10.5px] text-meta dark:text-panel-dim">admin</span>
			</div>
			<p className="mb-3.5 max-w-[620px] text-[13px] leading-[1.55] text-subtle dark:text-panel-body">
				Connect a Slack app to run agents and deliver their responses in Slack.
			</p>
			<div className="overflow-hidden rounded-[10px] border border-border bg-card dark:border-white/10">
				<div className="space-y-5 px-4 py-4">
					<div className="flex items-center justify-between gap-4">
						<div>
							<div className="text-[13px] font-semibold text-foreground">
								Slack
							</div>
							<div className="text-[11.5px] text-meta">
								{settings.isConfigured
									? `Configured, bot token ending in ${settings.botTokenLast4}`
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
								<span className={labelClass}>Bot token</span>
								<Input
									type="password"
									value={botToken}
									onChange={(event) => {
										setBotToken(event.target.value);
									}}
									placeholder={
										settings.isConfigured
											? "Leave blank to keep current"
											: "xoxb-…"
									}
								/>
							</label>
							<label className="block">
								<span className={labelClass}>Signing secret</span>
								<Input
									type="password"
									value={signingSecret}
									onChange={(event) => {
										setSigningSecret(event.target.value);
									}}
									placeholder={
										settings.isConfigured ? "Leave blank to keep current" : ""
									}
								/>
							</label>
							<label className="block">
								<span className={labelClass}>Events request URL</span>
								<Input
									readOnly
									value={settings.eventsUrl}
									className="font-mono"
								/>
							</label>
							<label className="block">
								<span className={labelClass}>Interactions request URL</span>
								<Input
									readOnly
									value={settings.interactionsUrl}
									className="font-mono"
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
