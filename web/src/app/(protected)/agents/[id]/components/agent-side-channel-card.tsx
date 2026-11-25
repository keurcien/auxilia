"use client";

import { useCallback, useEffect, useState } from "react";
import { Plus, Settings2 } from "lucide-react";
import { useConfirmDialog } from "@/components/providers/dialog-provider";
import { SlackLogo } from "@/components/slack-logo";
import { TelegramLogo } from "@/components/telegram-logo";
import { WhatsAppLogo } from "@/components/whatsapp-logo";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { getApiErrorMessage } from "@/lib/api/errors";
import * as agentsApi from "@/lib/api/resources/agents";
import { handleKeyboardListNavigation } from "@/lib/keyboard-list-navigation";
import { matchesQuery } from "@/lib/quick-search";
import { useAppearanceStore } from "@/stores/appearance-store";
import type {
	AgentSlackBotSettings,
	AgentSlackBotSettingsUpdate,
	AgentTelegramBotSettings,
	AgentTelegramBotSettingsUpdate,
	AgentWhatsAppSettings,
	AgentWhatsAppSettingsUpdate,
} from "@/types/agents";
import AgentSlackBotDialog from "./agent-slack-bot-dialog";
import AgentTelegramBotDialog from "./agent-telegram-bot-dialog";
import AgentWhatsAppDialog from "./agent-whatsapp-dialog";

interface Props {
	agentId: string;
	canManage: boolean;
	readOnly: boolean;
	onCountChange?: (count: number) => void;
	/** Quick search: only the connections matching it are shown. */
	query?: string;
}

type SideChannelConnection =
	| {
			kind: "slack";
			name: string;
			connection: AgentSlackBotSettings;
	  }
	| {
			kind: "telegram";
			name: string;
			connection: AgentTelegramBotSettings;
	  }
	| {
			kind: "whatsapp";
			name: string;
			connection: AgentWhatsAppSettings;
	  };

export default function AgentSideChannelCard({
	agentId,
	canManage,
	readOnly,
	onCountChange,
	query = "",
}: Props) {
	const confirmDialog = useConfirmDialog();
	const appName = useAppearanceStore((state) => state.appearance.appName);
	const [slackConnections, setSlackConnections] = useState<
		AgentSlackBotSettings[]
	>([]);
	const [slackSetup, setSlackSetup] = useState<AgentSlackBotSettings | null>(
		null,
	);
	const [selectedSlack, setSelectedSlack] =
		useState<AgentSlackBotSettings | null>(null);
	const [telegramConnections, setTelegramConnections] = useState<
		AgentTelegramBotSettings[]
	>([]);
	const [telegramSetup, setTelegramSetup] =
		useState<AgentTelegramBotSettings | null>(null);
	const [selectedTelegram, setSelectedTelegram] =
		useState<AgentTelegramBotSettings | null>(null);
	const [whatsAppConnections, setWhatsAppConnections] = useState<
		AgentWhatsAppSettings[]
	>([]);
	const [whatsAppSetup, setWhatsAppSetup] =
		useState<AgentWhatsAppSettings | null>(null);
	const [selectedWhatsApp, setSelectedWhatsApp] =
		useState<AgentWhatsAppSettings | null>(null);
	const [loading, setLoading] = useState(true);
	const [loadError, setLoadError] = useState<string | null>(null);
	const [pickerOpen, setPickerOpen] = useState(false);
	const [slackDialogOpen, setSlackDialogOpen] = useState(false);
	const [telegramDialogOpen, setTelegramDialogOpen] = useState(false);
	const [whatsAppDialogOpen, setWhatsAppDialogOpen] = useState(false);
	const [saving, setSaving] = useState(false);
	const [saveError, setSaveError] = useState<string | null>(null);

	const load = useCallback(async () => {
		setLoading(true);
		setLoadError(null);
		const results = await Promise.allSettled([
			agentsApi.listAgentSlackBots(agentId),
			agentsApi.getAgentSlackBotSetup(agentId),
			agentsApi.listAgentTelegramBots(agentId),
			agentsApi.getAgentTelegramBotSetup(agentId),
			agentsApi.listAgentWhatsAppConnections(agentId),
			agentsApi.getAgentWhatsAppSetup(agentId),
		]);
		const [
			slackConnectionsResult,
			slackSetupResult,
			telegramConnectionsResult,
			telegramSetupResult,
			whatsAppConnectionsResult,
			whatsAppSetupResult,
		] = results;
		if (slackConnectionsResult.status === "fulfilled") {
			setSlackConnections(slackConnectionsResult.value);
		}
		if (slackSetupResult.status === "fulfilled") {
			setSlackSetup(slackSetupResult.value);
		}
		if (telegramConnectionsResult.status === "fulfilled") {
			setTelegramConnections(telegramConnectionsResult.value);
		}
		if (telegramSetupResult.status === "fulfilled") {
			setTelegramSetup(telegramSetupResult.value);
		}
		if (whatsAppConnectionsResult.status === "fulfilled") {
			setWhatsAppConnections(whatsAppConnectionsResult.value);
		}
		if (whatsAppSetupResult.status === "fulfilled") {
			setWhatsAppSetup(whatsAppSetupResult.value);
		}
		const failed = results.find((result) => result.status === "rejected");
		if (failed?.status === "rejected") {
			setLoadError(
				getApiErrorMessage(
					failed.reason,
					"Some side-channel connections could not be loaded.",
				),
			);
		}
		setLoading(false);
	}, [agentId]);

	useEffect(() => {
		const timeoutId = window.setTimeout(() => {
			void load();
		}, 0);
		return () => {
			window.clearTimeout(timeoutId);
		};
	}, [load]);

	const openSlack = (settings: AgentSlackBotSettings) => {
		setSaveError(null);
		setSelectedSlack(settings);
		setSlackDialogOpen(true);
	};

	const openTelegram = (settings: AgentTelegramBotSettings) => {
		setSaveError(null);
		setSelectedTelegram(settings);
		setTelegramDialogOpen(true);
	};

	const openWhatsApp = (settings: AgentWhatsAppSettings) => {
		setSaveError(null);
		setSelectedWhatsApp(settings);
		setWhatsAppDialogOpen(true);
	};

	const saveSlack = async (update: AgentSlackBotSettingsUpdate) => {
		if (!selectedSlack) return;
		setSaving(true);
		setSaveError(null);
		try {
			const updated = selectedSlack.id
				? await agentsApi.updateAgentSlackBot(
						agentId,
						selectedSlack.id,
						update,
					)
				: await agentsApi.createAgentSlackBot(agentId, update);
			setSlackConnections((current) =>
				selectedSlack.id
					? current.map((connection) =>
							connection.id === updated.id ? updated : connection,
						)
					: [...current, updated],
			);
			setSlackDialogOpen(false);
			setSelectedSlack(null);
		} catch (error: unknown) {
			setSaveError(
				getApiErrorMessage(error, "Could not save the Slack connection."),
			);
		} finally {
			setSaving(false);
		}
	};

	const saveTelegram = async (update: AgentTelegramBotSettingsUpdate) => {
		if (!selectedTelegram) return;
		setSaving(true);
		setSaveError(null);
		try {
			const updated = selectedTelegram.id
				? await agentsApi.updateAgentTelegramBot(
						agentId,
						selectedTelegram.id,
						update,
					)
				: await agentsApi.createAgentTelegramBot(agentId, update);
			setTelegramConnections((current) =>
				selectedTelegram.id
					? current.map((connection) =>
							connection.id === updated.id ? updated : connection,
						)
					: [...current, updated],
			);
			setTelegramDialogOpen(false);
			setSelectedTelegram(null);
		} catch (error: unknown) {
			setSaveError(
				getApiErrorMessage(error, "Could not save the Telegram connection."),
			);
		} finally {
			setSaving(false);
		}
	};

	const saveWhatsApp = async (update: AgentWhatsAppSettingsUpdate) => {
		if (!selectedWhatsApp) return;
		setSaving(true);
		setSaveError(null);
		try {
			const updated = selectedWhatsApp.id
				? await agentsApi.updateAgentWhatsAppConnection(
						agentId,
						selectedWhatsApp.id,
						update,
					)
				: await agentsApi.createAgentWhatsAppConnection(agentId, update);
			setWhatsAppConnections((current) =>
				selectedWhatsApp.id
					? current.map((connection) =>
							connection.id === updated.id ? updated : connection,
						)
					: [...current, updated],
			);
			setWhatsAppDialogOpen(false);
			setSelectedWhatsApp(null);
		} catch (error: unknown) {
			setSaveError(
				getApiErrorMessage(error, "Could not save the WhatsApp connection."),
			);
		} finally {
			setSaving(false);
		}
	};

	const disconnectSlack = async (connection: AgentSlackBotSettings) => {
		if (
			!connection.id ||
			!(await confirmDialog({
				title: `Disconnect ${connection.slackTeamName ?? "this Slack workspace"}?`,
				description: `New Slack messages will stop reaching the agent. Existing ${appName} threads remain available.`,
				confirmLabel: "Disconnect",
				destructive: true,
			}))
		) {
			return;
		}
		setSaving(true);
		try {
			await agentsApi.deleteAgentSlackBot(agentId, connection.id);
			setSlackConnections((current) =>
				current.filter((item) => item.id !== connection.id),
			);
			setSlackDialogOpen(false);
			setSelectedSlack(null);
		} catch (error: unknown) {
			setLoadError(
				getApiErrorMessage(error, "Could not disconnect the Slack bot."),
			);
		} finally {
			setSaving(false);
		}
	};

	const disconnectTelegram = async (
		connection: AgentTelegramBotSettings,
	) => {
		if (
			!connection.id ||
			!(await confirmDialog({
				title: `Disconnect @${connection.botUsername ?? "this Telegram bot"}?`,
				description: `New Telegram messages will stop reaching the agent. Existing ${appName} threads remain available.`,
				confirmLabel: "Disconnect",
				destructive: true,
			}))
		) {
			return;
		}
		setSaving(true);
		try {
			await agentsApi.deleteAgentTelegramBot(agentId, connection.id);
			setTelegramConnections((current) =>
				current.filter((item) => item.id !== connection.id),
			);
			setTelegramDialogOpen(false);
			setSelectedTelegram(null);
		} catch (error: unknown) {
			setLoadError(
				getApiErrorMessage(error, "Could not disconnect the Telegram bot."),
			);
		} finally {
			setSaving(false);
		}
	};

	const disconnectWhatsApp = async (connection: AgentWhatsAppSettings) => {
		if (
			!connection.id ||
			!(await confirmDialog({
				title: `Disconnect ${connection.displayPhoneNumber ?? "this WhatsApp number"}?`,
				description: `New WhatsApp messages will stop reaching the agent. Existing ${appName} threads remain available.`,
				confirmLabel: "Disconnect",
				destructive: true,
			}))
		) {
			return;
		}
		setSaving(true);
		try {
			await agentsApi.deleteAgentWhatsAppConnection(agentId, connection.id);
			setWhatsAppConnections((current) =>
				current.filter((item) => item.id !== connection.id),
			);
			setWhatsAppDialogOpen(false);
			setSelectedWhatsApp(null);
		} catch (error: unknown) {
			setLoadError(
				getApiErrorMessage(error, "Could not disconnect WhatsApp."),
			);
		} finally {
			setSaving(false);
		}
	};

	const totalConnections =
		slackConnections.length +
		telegramConnections.length +
		whatsAppConnections.length;
	const sortedConnections: SideChannelConnection[] = [
		...slackConnections.map((connection) => ({
			kind: "slack" as const,
			name: connection.slackTeamName ?? "Slack workspace",
			connection,
		})),
		...telegramConnections.map((connection) => ({
			kind: "telegram" as const,
			name: connection.botUsername ?? "Telegram bot",
			connection,
		})),
		...whatsAppConnections.map((connection) => ({
			kind: "whatsapp" as const,
			name: connection.verifiedName ?? "WhatsApp",
			connection,
		})),
	].sort((a, b) => a.name.localeCompare(b.name));
	const visibleConnections = sortedConnections.filter((item) =>
		matchesQuery(
			query,
			item.kind,
			item.name,
			item.kind === "whatsapp"
				? item.connection.displayPhoneNumber
				: item.connection.botName,
		),
	);

	useEffect(() => {
		onCountChange?.(totalConnections);
	}, [onCountChange, totalConnections]);

	const statusLabel = (connection: {
		workspaceEnabled: boolean;
		enabled: boolean;
	}) =>
		!connection.workspaceEnabled
			? "Workspace disabled"
			: connection.enabled
				? "Connected"
				: "Paused";

	const canAdd = Boolean(slackSetup || telegramSetup || whatsAppSetup);

	return (
		<section className="mt-8">
			<div className="mb-2 flex items-center justify-between gap-4">
				<span className="text-[10.5px] font-semibold text-subtle dark:text-panel-dim">
					Side channels{" "}
					<span className="text-meta dark:text-panel-dim">
						{totalConnections}
					</span>
				</span>
				{canManage && !readOnly && canAdd && (
					<button
						type="button"
						onClick={() => {
							setPickerOpen(true);
						}}
						className="flex shrink-0 cursor-pointer items-center gap-1 whitespace-nowrap text-[12.5px] font-semibold text-petrol transition-opacity hover:opacity-80 dark:text-panel-terminal"
					>
						<Plus className="size-3" />
						Add side-channel
					</button>
				)}
			</div>
			<p className="mb-3 text-[12px] leading-5 text-meta">
				Let people operate this agent from external conversations.
			</p>

			<div
				className={`overflow-hidden rounded-[10px] border ${
					!loading && totalConnections === 0
						? "border-dashed border-input"
						: "border-border bg-card dark:border-white/10"
				}`}
			>
				{loading ? (
					<div className="px-3.5 py-4 text-[11px] text-meta">
						Checking connections…
					</div>
				) : totalConnections === 0 ? (
					<div className="px-4 py-8 text-center text-[13px] text-meta dark:text-panel-dim">
						No side channels configured
					</div>
				) : visibleConnections.length === 0 ? (
					<div className="px-4 py-8 text-center text-[13px] text-meta dark:text-panel-dim">
						No side channels match “{query.trim()}”
					</div>
				) : (
					<>
						{visibleConnections.map((item, index) => {
							const secondaryLabel =
								item.kind === "whatsapp"
									? item.connection.displayPhoneNumber
									: item.connection.botName;
							const { connection } = item;
							return (
								<div
									key={`${item.kind}-${connection.id}`}
									className={`flex items-center gap-3 px-3.5 py-3 ${
										index > 0 ? "border-t border-hairline" : ""
									}`}
								>
									{item.kind === "slack" ? (
										<SlackLogo className="size-8 shadow-none" />
									) : (
										<span className="flex size-8 shrink-0 items-center justify-center rounded-[8px] border border-border bg-background">
											{item.kind === "telegram" ? (
												<TelegramLogo className="size-[62%]" />
											) : (
												<WhatsAppLogo className="size-[62%]" />
											)}
										</span>
									)}
									<div className="min-w-0 flex-1">
										<p className="truncate text-[12.5px] font-semibold text-foreground">
											{item.kind === "telegram" ? `@${item.name}` : item.name}
										</p>
										{secondaryLabel && (
											<p className="truncate text-[10.5px] text-meta">
												{secondaryLabel}
											</p>
										)}
									</div>
									<span className="shrink-0 whitespace-nowrap rounded-[4px] bg-success-bg px-2 py-0.5 text-[9.5px] font-semibold text-success dark:bg-emerald-950 dark:text-emerald-300">
										{statusLabel(connection)}
									</span>
									{canManage && !readOnly && (
										<button
											type="button"
											onClick={() => {
												if (item.kind === "slack") {
													openSlack(item.connection);
												} else if (item.kind === "telegram") {
													openTelegram(item.connection);
												} else {
													openWhatsApp(item.connection);
												}
											}}
											className="flex shrink-0 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-[6px] border border-input bg-background px-2.5 py-1.5 text-[11px] font-semibold text-foreground transition-colors hover:border-border-hover"
										>
											<Settings2 className="size-3" />
											Configure
										</button>
									)}
								</div>
							);
						})}
					</>
				)}
				{loadError && (
					<div className="border-t border-border bg-destructive/5 px-3.5 py-2.5 dark:border-white/10">
						<p className="text-[10.5px] text-destructive">{loadError}</p>
						<button
							type="button"
							onClick={() => {
								void load();
							}}
							className="mt-1 cursor-pointer whitespace-nowrap text-[10.5px] font-semibold text-petrol hover:underline"
						>
							Retry
						</button>
					</div>
				)}
			</div>

			<Dialog open={pickerOpen} onOpenChange={setPickerOpen}>
				<DialogContent
					className="gap-0 overflow-hidden p-0 sm:max-w-[480px]"
					onKeyDown={handleKeyboardListNavigation}
				>
					<DialogHeader className="border-b border-border px-5 py-4 pr-14 dark:border-white/10">
						<DialogTitle>Add side-channel</DialogTitle>
						<DialogDescription className="mt-0.5">
							Choose where people can talk to this agent.
						</DialogDescription>
					</DialogHeader>
					<div className="space-y-2.5 p-5">
						{slackSetup && (
							<ProviderOption
								label="Slack"
								description="Install a dedicated bot in a Slack workspace."
								icon={<SlackLogo className="size-10 shadow-none" />}
								onClick={() => {
									setPickerOpen(false);
									openSlack(slackSetup);
								}}
							/>
						)}
						{telegramSetup && (
							<ProviderOption
								label="Telegram"
								description="Connect a BotFather bot for direct messages and groups."
								icon={
									<span className="flex size-10 shrink-0 items-center justify-center rounded-[8px] border border-border bg-background shadow-sm dark:border-white/10">
										<TelegramLogo className="size-[62%]" />
									</span>
								}
								onClick={() => {
									setPickerOpen(false);
									openTelegram(telegramSetup);
								}}
							/>
						)}
						{whatsAppSetup && (
							<ProviderOption
								label="WhatsApp"
								description="Connect a dedicated Meta app and Cloud API phone number."
								icon={
									<span className="flex size-10 shrink-0 items-center justify-center rounded-[8px] border border-border bg-background shadow-sm dark:border-white/10">
										<WhatsAppLogo className="size-[62%]" />
									</span>
								}
								onClick={() => {
									setPickerOpen(false);
									openWhatsApp(whatsAppSetup);
								}}
							/>
						)}
					</div>
				</DialogContent>
			</Dialog>

			{selectedSlack && slackDialogOpen && (
				<AgentSlackBotDialog
					key={selectedSlack.id ?? "new-slack-channel"}
					open={slackDialogOpen}
					onOpenChange={(open) => {
						setSlackDialogOpen(open);
						if (!open) setSelectedSlack(null);
					}}
					settings={selectedSlack}
					saving={saving}
					error={saveError}
					onSave={saveSlack}
					onDisconnect={
						selectedSlack.id
							? () => disconnectSlack(selectedSlack)
							: undefined
					}
				/>
			)}
			{selectedTelegram && telegramDialogOpen && (
				<AgentTelegramBotDialog
					key={selectedTelegram.id ?? "new-telegram-channel"}
					open={telegramDialogOpen}
					onOpenChange={(open) => {
						setTelegramDialogOpen(open);
						if (!open) setSelectedTelegram(null);
					}}
					settings={selectedTelegram}
					saving={saving}
					error={saveError}
					onSave={saveTelegram}
					onDisconnect={
						selectedTelegram.id
							? () => disconnectTelegram(selectedTelegram)
							: undefined
					}
				/>
			)}
			{selectedWhatsApp && whatsAppDialogOpen && (
				<AgentWhatsAppDialog
					key={selectedWhatsApp.id ?? "new-whatsapp-channel"}
					open={whatsAppDialogOpen}
					onOpenChange={(open) => {
						setWhatsAppDialogOpen(open);
						if (!open) setSelectedWhatsApp(null);
					}}
					settings={selectedWhatsApp}
					saving={saving}
					error={saveError}
					onSave={saveWhatsApp}
					onDisconnect={
						selectedWhatsApp.id
							? () => disconnectWhatsApp(selectedWhatsApp)
							: undefined
					}
				/>
			)}
		</section>
	);
}

function ProviderOption({
	label,
	description,
	icon,
	onClick,
}: {
	label: string;
	description: string;
	icon: React.ReactNode;
	onClick: () => void;
}) {
	return (
		<button
			type="button"
			data-keyboard-option="true"
			onClick={onClick}
			className="group flex w-full cursor-pointer items-center gap-3 rounded-[10px] border border-border bg-card p-3.5 text-left transition-all hover:border-petrol/35 hover:bg-petrol/[0.035] dark:border-white/10"
		>
			{icon}
			<span className="min-w-0 flex-1">
				<span className="block text-[13px] font-semibold text-foreground">
					{label}
				</span>
				<span className="mt-0.5 block text-[10.5px] leading-4 text-meta">
					{description}
				</span>
			</span>
			<span className="flex size-7 shrink-0 items-center justify-center rounded-[7px] border border-input bg-background text-subtle transition-colors group-hover:border-petrol/35 group-hover:text-petrol">
				<Plus className="size-3.5" />
			</span>
		</button>
	);
}
