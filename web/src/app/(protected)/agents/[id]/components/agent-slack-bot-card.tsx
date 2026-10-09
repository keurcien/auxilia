"use client";

import { useCallback, useEffect, useState } from "react";
import { MessageCircleMore, Settings2, Unplug } from "lucide-react";
import { useConfirmDialog } from "@/components/providers/dialog-provider";
import { SlackLogo } from "@/components/slack-logo";
import { getApiErrorMessage } from "@/lib/api/errors";
import * as agentsApi from "@/lib/api/resources/agents";
import { useAppearanceStore } from "@/stores/appearance-store";
import type {
	AgentSlackBotSettings,
	AgentSlackBotSettingsUpdate,
} from "@/types/agents";
import AgentSlackBotDialog from "./agent-slack-bot-dialog";

interface Props {
	agentId: string;
	canManage: boolean;
}

export default function AgentSlackBotCard({ agentId, canManage }: Props) {
	const confirmDialog = useConfirmDialog();
	const appName = useAppearanceStore((state) => state.appearance.appName);
	const [settings, setSettings] = useState<AgentSlackBotSettings | null>(null);
	const [loading, setLoading] = useState(true);
	const [loadError, setLoadError] = useState<string | null>(null);
	const [dialogOpen, setDialogOpen] = useState(false);
	const [saving, setSaving] = useState(false);
	const [saveError, setSaveError] = useState<string | null>(null);

	const load = useCallback(async () => {
		setLoading(true);
		setLoadError(null);
		try {
			setSettings(await agentsApi.getAgentSlackBot(agentId));
		} catch (error: unknown) {
			setLoadError(getApiErrorMessage(error, "Could not load the Slack bot."));
		} finally {
			setLoading(false);
		}
	}, [agentId]);

	useEffect(() => {
		const timeoutId = window.setTimeout(() => {
			void load();
		}, 0);
		return () => {
			window.clearTimeout(timeoutId);
		};
	}, [load]);

	const save = async (update: AgentSlackBotSettingsUpdate) => {
		setSaving(true);
		setSaveError(null);
		try {
			const updated = await agentsApi.updateAgentSlackBot(agentId, update);
			setSettings(updated);
			setDialogOpen(false);
		} catch (error: unknown) {
			setSaveError(
				getApiErrorMessage(error, "Could not save the Slack connection."),
			);
		} finally {
			setSaving(false);
		}
	};

	const disconnect = async () => {
		if (
			!(await confirmDialog({
				title: "Disconnect this Slack bot?",
				description:
					`New Slack messages will stop reaching this agent. Existing ${appName} threads remain available.`,
				confirmLabel: "Disconnect",
				destructive: true,
			}))
		) {
			return;
		}
		setSaving(true);
		try {
			setSettings(await agentsApi.deleteAgentSlackBot(agentId));
		} catch (error: unknown) {
			setLoadError(
				getApiErrorMessage(error, "Could not disconnect the Slack bot."),
			);
		} finally {
			setSaving(false);
		}
	};

	const status = !settings?.isConfigured
		? "Not connected"
		: !settings.workspaceEnabled
			? "Workspace integration disabled"
			: settings.enabled
				? `Connected${settings.slackTeamName ? ` to ${settings.slackTeamName}` : ""} with ****${settings.botTokenLast4 ?? "—"}`
				: "Connection paused";

	return (
		<section className="mt-8">
			<div className="mb-2">
				<span className="text-[10.5px] font-semibold text-subtle dark:text-panel-dim">
					Channels
				</span>
			</div>
			<p className="mb-3 text-[12px] leading-5 text-meta">
				Let people operate this agent from an external conversation.
			</p>

			<div className="overflow-hidden rounded-[10px] border border-border bg-card dark:border-white/10">
				<div className="flex items-center gap-3 px-3.5 py-3">
					<SlackLogo className="size-8 shadow-none" />
					<div className="min-w-0 flex-1">
						<div className="flex items-center gap-2">
							<p className="text-[12.5px] font-semibold text-foreground">
								Slack bot
							</p>
							{settings?.isConfigured && (
								<span
									className={`size-1.5 rounded-full ${
										settings.enabled && settings.workspaceEnabled
											? "bg-emerald-500"
											: "bg-amber-500"
									}`}
								/>
							)}
						</div>
						<p className="mt-0.5 truncate text-[10.5px] text-meta">
							{loading ? "Checking connection…" : status}
						</p>
					</div>
					{canManage && settings && (
						<div className="flex items-center gap-2">
							{settings.isConfigured && (
								<button
									type="button"
									disabled={saving}
									onClick={() => {
										void disconnect();
									}}
									className="flex cursor-pointer items-center gap-1 text-[10.5px] font-semibold text-destructive hover:underline disabled:opacity-50"
								>
									<Unplug className="size-3" />
									Disconnect
								</button>
							)}
							<button
								type="button"
								onClick={() => {
									setSaveError(null);
									setDialogOpen(true);
								}}
								className="flex cursor-pointer items-center gap-1.5 rounded-[6px] border border-input bg-background px-2.5 py-1.5 text-[11px] font-semibold text-foreground transition-colors hover:border-border-hover"
							>
								{settings.isConfigured ? (
									<Settings2 className="size-3" />
								) : (
									<MessageCircleMore className="size-3" />
								)}
								{settings.isConfigured ? "Configure" : "Connect"}
							</button>
						</div>
					)}
				</div>

				{loadError && (
					<div className="border-t border-border bg-destructive/5 px-3.5 py-2.5 dark:border-white/10">
						<p className="text-[10.5px] text-destructive">{loadError}</p>
						<button
							type="button"
							onClick={() => {
								void load();
							}}
							className="mt-1 cursor-pointer text-[10.5px] font-semibold text-petrol hover:underline"
						>
							Retry
						</button>
					</div>
				)}

			</div>

			{settings && dialogOpen && (
				<AgentSlackBotDialog
					open={dialogOpen}
					onOpenChange={setDialogOpen}
					settings={settings}
					saving={saving}
					error={saveError}
					onSave={save}
				/>
			)}
		</section>
	);
}
