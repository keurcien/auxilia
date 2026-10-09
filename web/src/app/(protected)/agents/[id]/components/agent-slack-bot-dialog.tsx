"use client";

import { useMemo, useState } from "react";
import {
	ArrowLeft,
	ArrowRight,
	ArrowUpRight,
	BookOpen,
	Check,
	Copy,
	MessageSquareText,
} from "lucide-react";
import {
	Dialog,
	DialogButton,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { SlackLogo } from "@/components/slack-logo";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useAppearanceStore } from "@/stores/appearance-store";
import type {
	AgentSlackBotSettings,
	AgentSlackBotSettingsUpdate,
} from "@/types/agents";

interface Props {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	settings: AgentSlackBotSettings;
	saving: boolean;
	error: string | null;
	onSave: (update: AgentSlackBotSettingsUpdate) => Promise<void>;
}

const scopes = [
	"app_mentions:read",
	"channels:history",
	"chat:write",
	"im:history",
	"users:read",
	"users:read.email",
];

function CopyValue({
	label,
	value,
	multiline = false,
}: {
	label: string;
	value: string;
	multiline?: boolean;
}) {
	const [copied, setCopied] = useState(false);

	const copy = () => {
		void navigator.clipboard.writeText(value).then(() => {
			setCopied(true);
			window.setTimeout(() => {
				setCopied(false);
			}, 1600);
		});
	};

	return (
		<div className="overflow-hidden rounded-[8px] border border-border bg-background dark:border-white/10">
			<div className="flex items-center justify-between border-b border-border px-3 py-1.5 dark:border-white/10">
				<span className="text-[10.5px] font-semibold uppercase tracking-[0.08em] text-meta">
					{label}
				</span>
				<button
					type="button"
					onClick={copy}
					className="flex cursor-pointer items-center gap-1.5 rounded-[5px] px-2 py-1 text-[12px] font-semibold text-petrol transition-colors hover:bg-petrol/10"
				>
					{copied ? <Check className="size-3" /> : <Copy className="size-3" />}
					{copied ? "Copied" : "Copy"}
				</button>
			</div>
			{multiline ? (
				<pre className="max-h-40 overflow-auto whitespace-pre-wrap break-all p-3 font-mono text-[11px] leading-[1.55] text-subtle">
					{value}
				</pre>
			) : (
				<code className="block truncate px-3 py-2.5 text-[12px] text-foreground">
					{value}
				</code>
			)}
		</div>
	);
}

function AgentSlackSetupGuide({
	manifest,
	settings,
	onDone,
}: {
	manifest: string;
	settings: AgentSlackBotSettings;
	onDone: () => void;
}) {
	const [activeStep, setActiveStep] = useState(0);
	const [setupMode, setSetupMode] = useState<"manifest" | "manual">("manifest");
	const appName = useAppearanceStore((state) => state.appearance.appName);
	const badgeClass =
		"rounded-[4px] border border-border bg-background px-1.5 py-0.5 text-[11.5px] text-foreground dark:border-white/10";

	const manifestSteps = [
		{
			title: "Apply the manifest",
			body: (
				<div>
					<p>
						For a new app, open{" "}
						<a
							href="https://api.slack.com/apps"
							target="_blank"
							rel="noreferrer"
							className="inline-flex items-center gap-1 font-semibold text-petrol hover:underline"
						>
							Slack API Apps
							<ArrowUpRight className="size-3" />
						</a>
						, choose <strong>Create New App → From a manifest</strong>, then
						select your workspace. For an existing app, open{" "}
						<strong>Settings → App Manifest</strong>. Paste this JSON and apply
						the changes.
					</p>
					<div className="mt-3">
						<CopyValue
							label="Slack app manifest"
							value={manifest}
							multiline
						/>
					</div>
				</div>
			),
		},
		{
			title: "Install the app",
			body: (
				<p>
					Slack normally asks you to install the app immediately after the
					manifest is applied, so this may already be done. If you skipped it
					or need to reinstall, open <strong>OAuth &amp; Permissions</strong>{" "}
					and click <strong>Install to Workspace</strong> or{" "}
					<strong>Reinstall to Workspace</strong>.
				</p>
			),
		},
		{
			title: "Copy the credentials",
			body: (
				<div className="space-y-3">
					<p>
						In <strong>OAuth &amp; Permissions</strong>, copy the{" "}
						<strong>Bot User OAuth Token</strong> beginning with{" "}
						<code className={badgeClass}>xoxb-</code>. Do not use the{" "}
						<code className={badgeClass}>xoxp-</code> user token.
					</p>
					<p>
						Then open <strong>Settings → Basic Information</strong>. Under{" "}
						<strong>App Credentials</strong>, click <strong>Show</strong> next
						to <strong>Signing Secret</strong> and copy it.
					</p>
				</div>
			),
		},
		{
			title: "Save and verify",
			body: (
				<div className="space-y-3">
					<p>
						Return to the configuration form, paste both credentials, enable
						the bot, and save.
					</p>
					<p>
						Then return to <strong>Event Subscriptions</strong> in Slack and
						click <strong>Retry</strong> if the Request URL is not yet
						verified. The manifest already configures the bot events,
						interactivity, permissions, and disables Socket Mode.
					</p>
				</div>
			),
		},
		{
			title: "Invite and mention",
			body: (
				<p>
					Invite the bot to a public channel, then mention it with your request.
					By default, every request in that thread must mention the bot. Replies
					remain visible to the channel, while {appName} checks that the sender
					can use this agent.
				</p>
			),
		},
	];

	const manualSteps = [
		{
			title: "Create the Slack app",
			body: (
				<p>
					Open{" "}
					<a
						href="https://api.slack.com/apps"
						target="_blank"
						rel="noreferrer"
						className="inline-flex items-center gap-1 font-semibold text-petrol hover:underline"
					>
						Slack API Apps
						<ArrowUpRight className="size-3" />
					</a>
					, choose <strong>Create New App → From scratch</strong>, then select
					your Slack workspace.
				</p>
			),
		},
		{
			title: "Disable Socket Mode",
			body: (
				<p>
					Open <strong>Settings → Socket Mode</strong> and turn it off. {appName}
					uses public HTTP callback URLs; Slack hides the Request URL fields
					while Socket Mode is enabled.
				</p>
			),
		},
		{
			title: "Add bot permissions",
			body: (
				<div>
					<p>
						In <strong>OAuth &amp; Permissions</strong>, add these{" "}
						<strong>Bot Token Scopes</strong>:
					</p>
					<div className="mt-2 flex flex-wrap gap-1.5">
						{scopes.map((scope) => (
							<code key={scope} className={badgeClass}>
								{scope}
							</code>
						))}
					</div>
				</div>
			),
		},
		{
			title: "Install and copy credentials",
			body: (
				<div className="space-y-3">
					<p>
						Install the app from <strong>OAuth &amp; Permissions</strong> and
						copy the <strong>Bot User OAuth Token</strong> beginning with{" "}
						<code className={badgeClass}>xoxb-</code>, not the{" "}
						<code className={badgeClass}>xoxp-</code> user token.
					</p>
					<p>
						In <strong>Settings → Basic Information → App Credentials</strong>,
						click <strong>Show</strong> beside <strong>Signing Secret</strong>{" "}
						and copy it.
					</p>
				</div>
			),
		},
		{
			title: "Subscribe to bot events",
			body: (
				<div>
					<p>
						In <strong>Event Subscriptions</strong>, enable events and paste
						the URL below. Under <strong>Subscribe to bot events</strong>,
						click <strong>Add Bot User Event</strong> and add{" "}
						<code className={badgeClass}>app_mention</code>,{" "}
						<code className={badgeClass}>message.channels</code>, and{" "}
						<code className={badgeClass}>message.im</code>. Do not use{" "}
						<strong>Subscribe to events on behalf of users</strong>.
					</p>
					<div className="mt-3">
						<CopyValue label="Events request URL" value={settings.eventsUrl} />
					</div>
				</div>
			),
		},
		{
			title: "Enable interactivity",
			body: (
				<div>
					<p>
						In <strong>Interactivity &amp; Shortcuts</strong>, enable
						interactivity and paste this URL into <strong>Request URL</strong>.
						If the field is missing, disable Socket Mode first.
					</p>
					<div className="mt-3">
						<CopyValue
							label="Interactions request URL"
							value={settings.interactionsUrl}
						/>
					</div>
				</div>
			),
		},
		{
			title: "Save and test",
			body: (
				<p>
					Return to the configuration form, save the{" "}
					<code className={badgeClass}>xoxb-</code> token and Signing Secret,
					then invite the bot to a public channel and mention it.
				</p>
			),
		},
	];

	const steps = setupMode === "manifest" ? manifestSteps : manualSteps;
	const step = steps[activeStep];
	const isLastStep = activeStep === steps.length - 1;

	return (
		<div className="grid min-h-[380px] grid-cols-[158px_minmax(0,1fr)] sm:grid-cols-[220px_minmax(0,1fr)]">
			<nav
				aria-label="Agent Slack setup steps"
				className="border-r border-border bg-card/45 py-4 dark:border-white/10 dark:bg-white/[0.025]"
			>
				<div className="mx-3 mb-4 grid grid-cols-2 rounded-[7px] border border-border bg-background p-1 dark:border-white/10 dark:bg-white/5">
					{(["manifest", "manual"] as const).map((mode) => (
						<button
							key={mode}
							type="button"
							onClick={() => {
								setSetupMode(mode);
								setActiveStep(0);
							}}
							className={`cursor-pointer rounded-[5px] px-2 py-1.5 text-[11px] font-semibold capitalize transition-colors ${
								setupMode === mode
									? "bg-card text-foreground shadow-sm"
									: "text-meta hover:text-foreground"
							}`}
						>
							{mode}
						</button>
					))}
				</div>
				<p className="mb-2 px-4 text-[10.5px] font-semibold uppercase tracking-[0.1em] text-meta sm:px-5">
					Setup
				</p>
				<ol>
					{steps.map((candidate, index) => (
						<li key={candidate.title}>
							<button
								type="button"
								aria-current={activeStep === index ? "step" : undefined}
								onClick={() => {
									setActiveStep(index);
								}}
								className={`group flex w-full cursor-pointer items-center gap-2.5 px-3 py-3 text-left transition-colors sm:px-4 ${
									activeStep === index ? "bg-petrol/[0.07]" : "hover:bg-hover"
								}`}
							>
								<span
									className={`flex size-6 shrink-0 items-center justify-center rounded-full border font-mono text-[10.5px] font-semibold transition-colors ${
										activeStep === index
											? "border-petrol bg-petrol text-white"
											: "border-border bg-card text-meta group-hover:text-foreground dark:border-white/10"
									}`}
								>
									{index + 1}
								</span>
								<span
									className={`min-w-0 text-[12.5px] leading-[1.3] font-semibold ${
										activeStep === index
											? "text-foreground"
											: "text-subtle"
									}`}
								>
									{candidate.title}
								</span>
							</button>
						</li>
					))}
				</ol>
			</nav>

			<section
				aria-live="polite"
				className="flex min-w-0 flex-col px-4 py-5 sm:px-6"
			>
				<div className="flex-1">
					<h3 className="text-[18px] font-bold text-foreground">{step.title}</h3>
					<div className="mt-3 text-[13.5px] leading-[1.65] text-subtle dark:text-panel-body">
						{step.body}
					</div>
				</div>

				<div className="mt-6 flex items-end justify-between gap-3 border-t border-border pt-4 dark:border-white/10">
					<p className="max-w-[250px] text-[11px] leading-[1.45] text-meta">
						Slack and {appName} members must use the same email address.
					</p>
					<DialogButton
						onClick={() => {
							if (isLastStep) {
								onDone();
								return;
							}
							setActiveStep((current) => current + 1);
						}}
					>
						{isLastStep ? "Done" : "Next"}
						{!isLastStep && <ArrowRight className="size-3.5" />}
					</DialogButton>
				</div>
			</section>
		</div>
	);
}

export default function AgentSlackBotDialog({
	open,
	onOpenChange,
	settings,
	saving,
	error,
	onSave,
}: Props) {
	const [view, setView] = useState<"configuration" | "guide">("configuration");
	const [enabled, setEnabled] = useState(settings.enabled);
	const [requireMentionInThreads, setRequireMentionInThreads] = useState(
		settings.requireMentionInThreads,
	);
	const [showToolCallouts, setShowToolCallouts] = useState(
		settings.showToolCallouts,
	);
	const [botToken, setBotToken] = useState("");
	const [signingSecret, setSigningSecret] = useState("");
	const manifest = useMemo(
		() => JSON.stringify(settings.manifest, null, 2),
		[settings.manifest],
	);

	const hasNewCredentials = Boolean(botToken.trim() || signingSecret.trim());
	const credentialsComplete = Boolean(botToken.trim() && signingSecret.trim());
	const canSave =
		!saving &&
		(settings.isConfigured || credentialsComplete) &&
		(!hasNewCredentials || credentialsComplete);

	const submit = async () => {
		if (!canSave) return;
		await onSave({
			enabled,
			requireMentionInThreads,
			showToolCallouts,
			...(credentialsComplete
				? {
						botToken: botToken.trim(),
						signingSecret: signingSecret.trim(),
					}
				: {}),
		});
	};

	const handleOpenChange = (nextOpen: boolean) => {
		if (!nextOpen) setView("configuration");
		onOpenChange(nextOpen);
	};

	return (
		<Dialog open={open} onOpenChange={saving ? undefined : handleOpenChange}>
			<DialogContent
				className={`gap-0 overflow-hidden p-0 ${
					view === "guide" ? "sm:max-w-[680px]" : "sm:max-w-[560px]"
				}`}
			>
				<DialogHeader className="border-b border-border px-5 py-4 pr-14 dark:border-white/10 sm:px-6">
					<div className="flex items-center gap-3">
						{view === "guide" ? (
							<button
								type="button"
								onClick={() => {
									setView("configuration");
								}}
								className="flex size-9 shrink-0 cursor-pointer items-center justify-center rounded-[9px] border border-border bg-card text-subtle transition-colors hover:text-foreground"
								aria-label="Back to configuration"
							>
								<ArrowLeft className="size-4" />
							</button>
						) : (
							<SlackLogo className="rounded-[9px] bg-card" />
						)}
						<div className="min-w-0">
							<DialogTitle>
								{view === "guide" ? "Create the Slack bot" : "Slack bot"}
							</DialogTitle>
							<DialogDescription className="mt-0.5">
								{view === "guide"
									? "One Slack app represents this agent."
									: "Give this agent its own identity in Slack."}
							</DialogDescription>
						</div>
					</div>
				</DialogHeader>

				{view === "configuration" ? (
					<>
						<div className="min-w-0 space-y-5 px-5 py-5 sm:px-6">
							{!settings.workspaceEnabled && (
								<div className="rounded-[8px] border border-amber-500/25 bg-amber-500/[0.07] px-3.5 py-3 text-[11.5px] leading-5 text-amber-800 dark:text-amber-200">
									Slack is disabled for the workspace. You can prepare this
									bot now, but an admin must enable Slack before it can answer.
								</div>
							)}

							<div className="overflow-hidden rounded-[9px] border border-border bg-sidebar dark:border-white/10">
								<div className="flex items-center justify-between gap-4 px-3.5 py-3">
									<div>
										<p className="text-[12.5px] font-semibold text-foreground">
											Accept Slack requests
										</p>
										<p className="mt-0.5 text-[10.5px] text-meta">
											Agent permissions are checked on every message.
										</p>
									</div>
									<Switch
										checked={enabled}
										onCheckedChange={setEnabled}
										className="cursor-pointer data-[state=checked]:bg-petrol"
									/>
								</div>
								<div className="flex items-center justify-between gap-4 border-t border-hairline px-3.5 py-3">
									<div>
										<p className="text-[12.5px] font-semibold text-foreground">
											Require @mention in channel threads
										</p>
										<p className="mt-0.5 text-[10.5px] text-meta">
											Ignore channel replies that do not mention this bot.
											Direct messages are always accepted.
										</p>
									</div>
									<Switch
										checked={requireMentionInThreads}
										onCheckedChange={setRequireMentionInThreads}
										className="cursor-pointer data-[state=checked]:bg-petrol"
									/>
								</div>
								<div className="flex items-center justify-between gap-4 border-t border-hairline px-3.5 py-3">
									<div>
										<p className="text-[12.5px] font-semibold text-foreground">
											Show tool callouts
										</p>
										<p className="mt-0.5 text-[10.5px] text-meta">
											Display tool names while the agent works. Turn off to
											keep only the textual response.
										</p>
									</div>
									<Switch
										checked={showToolCallouts}
										onCheckedChange={setShowToolCallouts}
										className="cursor-pointer data-[state=checked]:bg-petrol"
									/>
								</div>
							</div>

							<button
								type="button"
								onClick={() => {
									setView("guide");
								}}
								className="flex w-full cursor-pointer items-center gap-3 rounded-[9px] border border-petrol/20 bg-petrol/[0.055] p-3.5 text-left transition-colors hover:bg-petrol/[0.09] dark:border-petrol/55 dark:bg-petrol/25 dark:hover:bg-petrol/35"
							>
								<BookOpen className="size-4 shrink-0 text-petrol dark:text-panel-terminal" />
								<span className="min-w-0 flex-1">
									<span className="block text-[12px] font-semibold text-petrol dark:text-panel-terminal">
										How to create and configure the Slack app
									</span>
									<span className="mt-0.5 block text-[10.5px] text-subtle dark:text-panel-body">
										Use the ready-to-copy manifest and callback URLs.
									</span>
								</span>
								<ArrowUpRight className="size-3.5 shrink-0 text-petrol dark:text-panel-terminal" />
							</button>

							<div className="grid gap-4 sm:grid-cols-2">
								<label className="block">
									<span className="mb-1.5 block text-[11px] font-semibold text-label">
										Bot User OAuth Token
									</span>
									<Input
										type="password"
										autoComplete="new-password"
										value={botToken}
										onChange={(event) => {
											setBotToken(event.target.value);
										}}
										placeholder={
											settings.isConfigured
												? `****${settings.botTokenLast4 ?? "—"}`
												: "xoxb-…"
										}
									/>
								</label>
								<label className="block">
									<span className="mb-1.5 block text-[11px] font-semibold text-label">
										Signing Secret
									</span>
									<Input
										type="password"
										autoComplete="new-password"
										value={signingSecret}
										onChange={(event) => {
											setSigningSecret(event.target.value);
										}}
										placeholder={
											settings.hasSigningSecret
												? "Leave blank to keep current"
												: "Signing secret"
										}
									/>
								</label>
							</div>

							{settings.isConfigured && (
								<div className="flex items-center gap-3 rounded-[8px] border border-border px-3.5 py-3 dark:border-white/10">
									<MessageSquareText className="size-4 text-petrol" />
									<div className="min-w-0">
										<p className="truncate text-[11.5px] font-semibold text-foreground">
											{settings.botName || "Slack bot"}
											{settings.slackTeamName
												? ` · ${settings.slackTeamName}`
												: ""}
										</p>
										<p className="mt-0.5 text-[10px] text-meta">
											Connected credentials are encrypted at rest.
										</p>
									</div>
								</div>
							)}

							{error && (
								<p className="rounded-[7px] bg-destructive/10 px-3 py-2 text-[11.5px] text-destructive">
									{error}
								</p>
							)}
						</div>
						<DialogFooter className="border-t border-border px-5 py-3.5 dark:border-white/10 sm:px-6">
							<DialogButton
								variant="outline"
								disabled={saving}
								onClick={() => {
									handleOpenChange(false);
								}}
							>
								Cancel
							</DialogButton>
							<DialogButton
								disabled={!canSave}
								onClick={() => {
									void submit();
								}}
							>
								{saving ? "Saving…" : "Save connection"}
							</DialogButton>
						</DialogFooter>
					</>
				) : (
					<AgentSlackSetupGuide
						manifest={manifest}
						settings={settings}
						onDone={() => {
							setView("configuration");
						}}
					/>
				)}
			</DialogContent>
		</Dialog>
	);
}
