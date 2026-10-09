"use client";

import { useCallback, useEffect, useState } from "react";
import { SlackLogo } from "@/components/slack-logo";
import { Switch } from "@/components/ui/switch";
import { getApiErrorMessage, isApiError } from "@/lib/api/errors";
import * as notificationsApi from "@/lib/api/resources/notifications";
import type { SlackNotificationSettings } from "@/types/notifications";

interface Props {
	onForbidden: () => void;
}

export default function WorkspaceMessaging({ onForbidden }: Props) {
	const [settings, setSettings] = useState<SlackNotificationSettings | null>(null);
	const [enabled, setEnabled] = useState(false);
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
				getApiErrorMessage(error, "Could not load Slack settings."),
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

	const toggleEnabled = async (checked: boolean) => {
		setEnabled(checked);
		setStatus(null);
		setSaving(true);
		try {
			const updated = await notificationsApi.updateSlackSettings({
				enabled: checked,
			});
			setSettings(updated);
			setStatus(
				checked ? "Slack integration enabled." : "Slack integration disabled.",
			);
		} catch (error: unknown) {
			setEnabled(!checked);
			if (isApiError(error) && error.status === 403) onForbidden();
			setStatus(
				isApiError(error) && error.detail
					? error.detail
					: "Could not update Slack settings.",
			);
		} finally {
			setSaving(false);
		}
	};

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
			<div className="h-32 animate-pulse rounded-[10px] border border-border bg-card" />
		);
	}

	return (
		<div>
			<div className="mb-1.5 flex items-center gap-2.5">
				<span className="text-[10.5px] font-semibold text-subtle dark:text-panel-dim">
					Messaging
				</span>
				<span className="text-[10.5px] text-meta dark:text-panel-dim">admin</span>
			</div>
			<p className="mb-3.5 max-w-[620px] text-[13px] leading-[1.55] text-subtle dark:text-panel-body">
				Enable or disable Slack bots for this workspace. Bot credentials and
				setup are managed directly from each agent.
			</p>

			<div className="overflow-hidden rounded-[10px] border border-border bg-card dark:border-white/10">
				<div className="flex items-center gap-3 px-4 py-4">
					<SlackLogo />
					<div className="min-w-0 flex-1">
						<p className="text-[13px] font-semibold text-foreground">
							Slack integration
						</p>
						<p className="mt-0.5 text-[11.5px] text-meta">
							{enabled
								? "Enabled for agent-specific bots"
								: "Disabled for all agent bots"}
						</p>
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
				{status && (
					<div className="border-t border-hairline px-4 py-3 text-[12px] text-subtle">
						{status}
					</div>
				)}
			</div>
		</div>
	);
}
