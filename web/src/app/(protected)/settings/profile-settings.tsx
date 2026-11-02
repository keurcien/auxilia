"use client";

import {
	Check,
	Copy,
	Download,
	KeyRound,
	Link2,
	Loader2,
	Menu,
	ShieldCheck,
	Unlink,
	UserRound,
	Volume2,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { SlackLogo } from "@/components/slack-logo";
import { TelegramLogo } from "@/components/telegram-logo";
import { WhatsAppLogo } from "@/components/whatsapp-logo";
import { ImageUpload } from "@/components/ui/image-upload";
import { Switch } from "@/components/ui/switch";
import { getApiErrorMessage } from "@/lib/api/errors";
import * as notificationsApi from "@/lib/api/resources/notifications";
import * as usersApi from "@/lib/api/resources/users";
import {
	setConfirmExternalLinks,
	setResponseSoundEnabled,
	setShowShortcutsInMenu,
	useConfirmExternalLinks,
	useResponseSoundEnabled,
	useShowShortcutsInMenu,
} from "@/lib/user-preferences";
import { useAgentsStore } from "@/stores/agents-store";
import { useAppearanceStore } from "@/stores/appearance-store";
import { useUserStore } from "@/stores/user-store";
import type { CurrentUser } from "@/types/auth";
import type {
	SlackIdentity,
	SlackLinkCode,
	TelegramIdentity,
	TelegramLinkCode,
	WhatsAppIdentity,
	WhatsAppLinkCode,
} from "@/types/notifications";

const inputClass =
	"w-full rounded-[8px] border border-input bg-card px-3 py-2.5 text-[13px] text-foreground outline-none transition-colors placeholder:text-meta focus:border-petrol";
const labelClass =
	"mb-1.5 block text-[10px] font-semibold text-subtle dark:text-panel-dim";

function Feedback({
	error,
	success,
}: {
	error: string | null;
	success: string | null;
}) {
	if (!error && !success) return null;
	return (
		<p
			className={`mt-3 text-[12px] font-medium ${
				error ? "text-destructive" : "text-petrol dark:text-panel-terminal"
			}`}
		>
			{error ?? success}
		</p>
	);
}

function CopyLinkButton({ command }: { command: string }) {
	const [copied, setCopied] = useState(false);

	const copy = async () => {
		await navigator.clipboard.writeText(command);
		setCopied(true);
		window.setTimeout(() => {
			setCopied(false);
		}, 2000);
	};

	return (
		<button
			type="button"
			onClick={() => {
				void copy();
			}}
			className="flex shrink-0 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-[6px] bg-primary px-3 py-1.5 text-[11.5px] font-semibold text-primary-foreground transition-opacity hover:opacity-90"
			aria-label={`Copy ${command}`}
		>
			{copied ? (
				<Check className="size-3.5" aria-hidden="true" />
			) : (
				<Copy className="size-3.5" aria-hidden="true" />
			)}
			{copied ? "Copied" : "Copy"}
		</button>
	);
}

function SectionHeading({
	icon,
	title,
	description,
}: {
	icon: React.ReactNode;
	title: string;
	description: string;
}) {
	return (
		<div className="mb-5 flex items-start gap-3">
			<span className="flex size-9 shrink-0 items-center justify-center rounded-[9px] border border-input bg-hover text-petrol dark:bg-white/5 dark:text-panel-terminal">
				{icon}
			</span>
			<div>
				<h2 className="text-[14px] font-semibold text-foreground">{title}</h2>
				<p className="mt-0.5 text-[12.5px] leading-5 text-subtle dark:text-panel-body">
					{description}
				</p>
			</div>
		</div>
	);
}

function BackupCodes({
	codes,
	onDone,
}: {
	codes: string[];
	onDone: () => void;
}) {
	const [copied, setCopied] = useState(false);
	const appName = useAppearanceStore((state) => state.appearance.appName);

	const copyCodes = async () => {
		await navigator.clipboard.writeText(codes.join("\n"));
		setCopied(true);
		setTimeout(() => {
			setCopied(false);
		}, 2000);
	};

	const downloadCodes = () => {
		const fileAppName =
			appName.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") ||
			"app";
		const content = [
			`${appName} backup codes`,
			"Each code can be used once.",
			"",
			...codes,
			"",
		].join("\n");
		const url = URL.createObjectURL(
			new Blob([content], { type: "text/plain;charset=utf-8" }),
		);
		const link = document.createElement("a");
		link.href = url;
		link.download = `backup-codes-${fileAppName}.txt`;
		link.click();
		URL.revokeObjectURL(url);
	};

	return (
		<div className="rounded-[10px] border border-petrol/30 bg-[#F2F8F8] p-4 dark:bg-petrol/10">
			<div className="flex items-start justify-between gap-4">
				<div>
					<p className="text-[13px] font-semibold text-foreground">
						Save your backup codes
					</p>
					<p className="mt-1 text-[12px] leading-5 text-subtle dark:text-panel-body">
						Each code works once. Store them somewhere safe before closing this panel.
					</p>
				</div>
				<div className="flex shrink-0 items-center gap-2">
					<button
						type="button"
						onClick={downloadCodes}
						className="flex cursor-pointer items-center gap-1.5 rounded-[7px] border border-input bg-card px-3 py-1.5 text-[12px] font-semibold text-petrol transition-colors hover:border-border-hover dark:border-white/10 dark:bg-white/[0.03] dark:text-panel-terminal dark:hover:border-white/20"
					>
						<Download className="size-3.5" />
						Download
					</button>
					<button
						type="button"
						onClick={() => {
							void copyCodes();
						}}
						className="flex cursor-pointer items-center gap-1.5 rounded-[7px] border border-input bg-card px-3 py-1.5 text-[12px] font-semibold text-petrol transition-colors hover:border-border-hover dark:border-white/10 dark:bg-white/[0.03] dark:text-panel-terminal dark:hover:border-white/20"
					>
						{copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
						{copied ? "Copied" : "Copy all"}
					</button>
				</div>
			</div>
			<div className="mt-4 grid grid-cols-2 gap-x-8 gap-y-2 rounded-[8px] border border-petrol/15 bg-white/70 px-4 py-3 dark:bg-black/10">
				{codes.map((code) => (
					<code key={code} className="font-mono text-[12.5px] text-foreground">
						{code}
					</code>
				))}
			</div>
			<button
				type="button"
				onClick={onDone}
				className="mt-4 cursor-pointer rounded-[7px] bg-petrol px-4 py-2 text-[12px] font-semibold text-white"
			>
				I have saved these codes
			</button>
		</div>
	);
}

function IdentityCard({ user }: { user: CurrentUser }) {
	const setUser = useUserStore((state) => state.setUser);
	const [firstName, setFirstName] = useState(user.firstName ?? user.name ?? "");
	const [lastName, setLastName] = useState(user.lastName ?? "");
	const [imageFile, setImageFile] = useState<File | null>(null);
	const [imageRemoved, setImageRemoved] = useState(false);
	const [saving, setSaving] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [success, setSuccess] = useState<string | null>(null);
	const currentImageUrl = user.imageRevision
		? usersApi.userImageUrl(user.id, user.imageRevision)
		: user.pictureUrl;

	const save = async () => {
		setSaving(true);
		setError(null);
		setSuccess(null);
		try {
			const updated = await usersApi.updateProfile({ firstName, lastName });
			let imageRevision = updated.imageRevision;
			if (imageFile) {
				imageRevision = await usersApi.uploadProfileImage(imageFile);
			} else if (imageRemoved && user.imageRevision) {
				await usersApi.deleteProfileImage();
				imageRevision = null;
			}
			const nextUser = {
				...updated,
				supervision: user.supervision,
				twoFactorEnforced: user.twoFactorEnforced,
				twoFactorRequired: user.twoFactorRequired,
				imageRevision,
			};
			setUser(nextUser);
			useAgentsStore.getState().updateOwnerSnapshot(nextUser.id, {
				id: nextUser.id,
				name: nextUser.name,
				email: nextUser.email,
				pictureUrl: nextUser.pictureUrl,
				imageRevision: nextUser.imageRevision,
			});
			setImageFile(null);
			setImageRemoved(false);
			setSuccess("Profile updated.");
		} catch (caught: unknown) {
			setError(getApiErrorMessage(caught, "Could not update your profile."));
		} finally {
			setSaving(false);
		}
	};

	return (
		<section className="rounded-[12px] border border-border bg-card p-5">
			<SectionHeading
				icon={<UserRound className="size-4" />}
				title="Personal details"
				description="Your name and avatar are visible to other workspace members."
			/>
			<ImageUpload
				currentUrl={currentImageUrl}
				file={imageFile}
				removed={imageRemoved}
				onFileChange={(file) => {
					setImageFile(file);
					setImageRemoved(false);
				}}
				onRemove={() => {
					setImageFile(null);
					setImageRemoved(true);
				}}
				label="Profile photo"
				previewShape="circle"
				removable={Boolean(user.imageRevision)}
				disabled={saving}
				className="mb-5"
			/>
			<div className="grid gap-4 sm:grid-cols-2">
				<label>
					<span className={labelClass}>First name</span>
					<input
						value={firstName}
						onChange={(event) => {
							setFirstName(event.target.value);
						}}
						maxLength={100}
						className={inputClass}
					/>
				</label>
				<label>
					<span className={labelClass}>Last name</span>
					<input
						value={lastName}
						onChange={(event) => {
							setLastName(event.target.value);
						}}
						maxLength={100}
						className={inputClass}
					/>
				</label>
			</div>
			<label className="mt-4 block">
				<span className={labelClass}>Email</span>
				<input value={user.email ?? ""} disabled className={`${inputClass} opacity-60`} />
			</label>
			<div className="mt-5 flex items-center justify-between">
				<Feedback error={error} success={success} />
				<button
					type="button"
					disabled={saving}
					onClick={() => {
						void save();
					}}
					className="ml-auto cursor-pointer rounded-[7px] bg-primary px-4 py-2 text-[12.5px] font-semibold text-primary-foreground transition-opacity hover:opacity-90 disabled:cursor-default disabled:opacity-50"
				>
					{saving ? "Saving…" : "Save profile"}
				</button>
			</div>
		</section>
	);
}

function ConnectedAccountsCard() {
	const [slackIdentity, setSlackIdentity] = useState<SlackIdentity | null>(null);
	const [slackLink, setSlackLink] = useState<SlackLinkCode | null>(null);
	const [telegramIdentity, setTelegramIdentity] =
		useState<TelegramIdentity | null>(null);
	const [telegramLink, setTelegramLink] = useState<TelegramLinkCode | null>(
		null,
	);
	const [whatsAppIdentity, setWhatsAppIdentity] =
		useState<WhatsAppIdentity | null>(null);
	const [whatsAppLink, setWhatsAppLink] = useState<WhatsAppLinkCode | null>(
		null,
	);
	type Channel = "slack" | "telegram" | "whatsapp";
	const [busy, setBusy] = useState<Channel | null>(null);
	const [checking, setChecking] = useState<Channel | null>(null);
	const [error, setError] = useState<string | null>(null);

	const load = useCallback(async () => {
		setError(null);
		const results = await Promise.allSettled([
			notificationsApi.getSlackIdentity(),
			notificationsApi.getTelegramIdentity(),
			notificationsApi.getWhatsAppIdentity(),
		]);
		const [slackResult, telegramResult, whatsAppResult] = results;
		if (slackResult.status === "fulfilled") setSlackIdentity(slackResult.value);
		if (telegramResult.status === "fulfilled") {
			setTelegramIdentity(telegramResult.value);
		}
		if (whatsAppResult.status === "fulfilled") {
			setWhatsAppIdentity(whatsAppResult.value);
		}
		const failed = results.find((result) => result.status === "rejected");
		if (failed?.status === "rejected") {
			setError(
				getApiErrorMessage(failed.reason, "Some connected accounts could not be loaded."),
			);
		}
	}, []);

	useEffect(() => {
		const timeout = window.setTimeout(() => {
			void load();
		}, 0);
		return () => {
			window.clearTimeout(timeout);
		};
	}, [load]);

	const generateSlackCode = async () => {
		setBusy("slack");
		setError(null);
		try {
			setSlackLink(await notificationsApi.createSlackLinkCode());
		} catch (caught: unknown) {
			setError(
				getApiErrorMessage(caught, "Could not create a Slack link code."),
			);
		} finally {
			setBusy(null);
		}
	};

	const unlinkSlack = async () => {
		setBusy("slack");
		setError(null);
		try {
			await notificationsApi.unlinkSlackIdentity();
			setSlackIdentity({ linked: false, workspaceCount: 0 });
			setSlackLink(null);
		} catch (caught: unknown) {
			setError(getApiErrorMessage(caught, "Could not unlink Slack."));
		} finally {
			setBusy(null);
		}
	};

	const generateTelegramCode = async () => {
		setBusy("telegram");
		setError(null);
		try {
			setTelegramLink(await notificationsApi.createTelegramLinkCode());
		} catch (caught: unknown) {
			setError(
				getApiErrorMessage(caught, "Could not create a Telegram link code."),
			);
		} finally {
			setBusy(null);
		}
	};

	const unlinkTelegram = async () => {
		setBusy("telegram");
		setError(null);
		try {
			await notificationsApi.unlinkTelegramIdentity();
			setTelegramIdentity({
				linked: false,
				username: null,
				displayName: null,
			});
			setTelegramLink(null);
		} catch (caught: unknown) {
			setError(getApiErrorMessage(caught, "Could not unlink Telegram."));
		} finally {
			setBusy(null);
		}
	};

	const generateWhatsAppCode = async () => {
		setBusy("whatsapp");
		setError(null);
		try {
			setWhatsAppLink(await notificationsApi.createWhatsAppLinkCode());
		} catch (caught: unknown) {
			setError(
				getApiErrorMessage(caught, "Could not create a WhatsApp link code."),
			);
		} finally {
			setBusy(null);
		}
	};

	const unlinkWhatsApp = async () => {
		setBusy("whatsapp");
		setError(null);
		try {
			await notificationsApi.unlinkWhatsAppIdentity();
			setWhatsAppIdentity({
				linked: false,
				phoneNumber: null,
				displayName: null,
			});
			setWhatsAppLink(null);
		} catch (caught: unknown) {
			setError(getApiErrorMessage(caught, "Could not unlink WhatsApp."));
		} finally {
			setBusy(null);
		}
	};

	const checkConnection = async (channel: Channel) => {
		setChecking(channel);
		try {
			await load();
		} finally {
			setChecking(null);
		}
	};

	const linkedName = telegramIdentity?.username
		? `@${telegramIdentity.username}`
		: (telegramIdentity?.displayName ?? "Telegram user");
	const whatsAppLinkedName =
		whatsAppIdentity?.displayName ??
		whatsAppIdentity?.phoneNumber ??
		"WhatsApp user";

	return (
		<section className="rounded-[12px] border border-border bg-card p-5">
			<SectionHeading
				icon={<Link2 className="size-4" />}
				title="Side-channel identities"
				description="See how messaging providers identify you when you message an agent."
			/>
			<div className="overflow-hidden rounded-[9px] border border-input">
				<div className="flex items-center gap-3 px-4 py-3.5">
					<SlackLogo />
					<div className="min-w-0 flex-1">
						<p className="text-[13px] font-semibold text-foreground">Slack</p>
						<p className="mt-0.5 text-[12px] text-subtle dark:text-panel-body">
							{slackIdentity?.linked
								? `Linked in ${slackIdentity.workspaceCount} Slack ${slackIdentity.workspaceCount === 1 ? "workspace" : "workspaces"}`
								: "Not linked"}
						</p>
					</div>
					{slackIdentity?.linked ? (
						<button
							type="button"
							disabled={busy !== null}
							onClick={() => {
								void unlinkSlack();
							}}
							className="flex cursor-pointer items-center gap-1.5 rounded-[7px] border border-input bg-card px-3 py-1.5 text-[12px] font-semibold text-destructive disabled:opacity-50"
						>
							<Unlink className="size-3.5" />
							Unlink
						</button>
					) : (
						<button
							type="button"
							disabled={busy !== null}
							onClick={() => {
								void generateSlackCode();
							}}
							className="cursor-pointer rounded-[7px] bg-petrol px-3 py-1.5 text-[12px] font-semibold text-white disabled:opacity-50"
						>
							{busy === "slack" ? "Generating…" : "Link Slack"}
						</button>
					)}
				</div>
				<div className="flex items-center gap-3 border-t border-hairline px-4 py-3.5">
					<span className="flex size-9 shrink-0 items-center justify-center rounded-[8px] border border-border bg-background shadow-sm dark:border-white/10">
						<TelegramLogo className="size-[62%]" />
					</span>
					<div className="min-w-0 flex-1">
						<p className="text-[13px] font-semibold text-foreground">
							Telegram
						</p>
						<p className="mt-0.5 text-[12px] text-subtle dark:text-panel-body">
							{telegramIdentity?.linked
								? `Linked as ${linkedName}`
								: "Not linked"}
						</p>
					</div>
					{telegramIdentity?.linked ? (
						<button
							type="button"
							disabled={busy !== null}
							onClick={() => {
								void unlinkTelegram();
							}}
							className="flex cursor-pointer items-center gap-1.5 rounded-[7px] border border-input bg-card px-3 py-1.5 text-[12px] font-semibold text-destructive disabled:opacity-50"
						>
							<Unlink className="size-3.5" />
							Unlink
						</button>
					) : (
						<button
							type="button"
							disabled={busy !== null}
							onClick={() => {
								void generateTelegramCode();
							}}
							className="cursor-pointer rounded-[7px] bg-petrol px-3 py-1.5 text-[12px] font-semibold text-white disabled:opacity-50"
						>
							{busy === "telegram" ? "Generating…" : "Link Telegram"}
						</button>
					)}
				</div>
				<div className="flex items-center gap-3 border-t border-hairline px-4 py-3.5">
					<span className="flex size-9 shrink-0 items-center justify-center rounded-[8px] border border-border bg-background shadow-sm dark:border-white/10">
						<WhatsAppLogo className="size-[62%]" />
					</span>
					<div className="min-w-0 flex-1">
						<p className="text-[13px] font-semibold text-foreground">
							WhatsApp
						</p>
						<p className="mt-0.5 text-[12px] text-subtle dark:text-panel-body">
							{whatsAppIdentity?.linked
								? `Linked as ${whatsAppLinkedName}`
								: "Not linked"}
						</p>
					</div>
					{whatsAppIdentity?.linked ? (
						<button
							type="button"
							disabled={busy !== null}
							onClick={() => {
								void unlinkWhatsApp();
							}}
							className="flex shrink-0 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-[7px] border border-input bg-card px-3 py-1.5 text-[12px] font-semibold text-destructive disabled:opacity-50"
						>
							<Unlink className="size-3.5" />
							Unlink
						</button>
					) : (
						<button
							type="button"
							disabled={busy !== null}
							onClick={() => {
								void generateWhatsAppCode();
							}}
							className="shrink-0 cursor-pointer whitespace-nowrap rounded-[7px] bg-petrol px-3 py-1.5 text-[12px] font-semibold text-white disabled:opacity-50"
						>
							{busy === "whatsapp" ? "Generating…" : "Link WhatsApp"}
						</button>
					)}
				</div>
			</div>
			{slackLink && !slackIdentity?.linked && (
				<div className="mt-3 rounded-[9px] border border-petrol/20 bg-petrol/[0.045] p-3 dark:border-petrol/50 dark:bg-petrol/15">
					<p className="text-[12px] leading-5 text-subtle dark:text-panel-body">
						Send{" "}
						<code className="rounded-[2px] border border-border bg-background px-1 py-px font-mono text-[11.5px] text-foreground">
							link {slackLink.code}
						</code>{" "}
						in a direct message to any Slack bot connected to this workspace.
						The code expires in 10 minutes and can only be used once.
					</p>
					<div className="mt-2 flex items-center gap-2">
						<CopyLinkButton command={`link ${slackLink.code}`} />
						<button
							type="button"
							disabled={checking !== null}
							onClick={() => {
								void checkConnection("slack");
							}}
							className="flex shrink-0 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-[6px] border border-input bg-card px-3 py-1.5 text-[11.5px] font-semibold text-foreground disabled:cursor-default disabled:opacity-60"
						>
							{checking === "slack" && (
								<Loader2
									className="size-3.5 animate-spin"
									aria-hidden="true"
								/>
							)}
							{checking === "slack" ? "Checking…" : "Check connection"}
						</button>
					</div>
				</div>
			)}
			{telegramLink && !telegramIdentity?.linked && (
				<div className="mt-3 rounded-[9px] border border-petrol/20 bg-petrol/[0.045] p-3 dark:border-petrol/50 dark:bg-petrol/15">
					<p className="text-[12px] leading-5 text-subtle dark:text-panel-body">
						Send{" "}
						<code className="rounded-[2px] border border-border bg-background px-1 py-px font-mono text-[11.5px] text-foreground">
							/link {telegramLink.code}
						</code>{" "}
						in a private chat with the bot.
						The code expires in 10 minutes and can only be used once.
					</p>
					<div className="mt-2 flex items-center gap-2">
						{telegramLink.deepLinkUrl && (
							<a
								href={telegramLink.deepLinkUrl}
								target="_blank"
								rel="noreferrer"
								className="rounded-[6px] bg-petrol px-3 py-1.5 text-[11.5px] font-semibold text-white"
							>
								Open Telegram
							</a>
						)}
						<CopyLinkButton command={`/link ${telegramLink.code}`} />
						<button
							type="button"
							disabled={checking !== null}
							onClick={() => {
								void checkConnection("telegram");
							}}
							className="flex cursor-pointer items-center gap-1.5 rounded-[6px] border border-input bg-card px-3 py-1.5 text-[11.5px] font-semibold text-foreground disabled:cursor-default disabled:opacity-60"
						>
							{checking === "telegram" && (
								<Loader2
									className="size-3.5 animate-spin"
									aria-hidden="true"
								/>
							)}
							{checking === "telegram" ? "Checking…" : "Check connection"}
						</button>
					</div>
				</div>
			)}
			{whatsAppLink && !whatsAppIdentity?.linked && (
				<div className="mt-3 rounded-[9px] border border-petrol/20 bg-petrol/[0.045] p-3 dark:border-petrol/50 dark:bg-petrol/15">
					<p className="text-[12px] leading-5 text-subtle dark:text-panel-body">
						Send{" "}
						<code className="rounded-[2px] border border-border bg-background px-1 py-px font-mono text-[11.5px] text-foreground">
							/link {whatsAppLink.code}
						</code>{" "}
						to the agent&apos;s WhatsApp number. The code expires in 10 minutes
						and can only be used once.
					</p>
					<div className="mt-2 flex items-center gap-2">
						{whatsAppLink.deepLinkUrl && (
							<a
								href={whatsAppLink.deepLinkUrl}
								target="_blank"
								rel="noreferrer"
								className="shrink-0 whitespace-nowrap rounded-[6px] bg-petrol px-3 py-1.5 text-[11.5px] font-semibold text-white"
							>
								Open WhatsApp
							</a>
						)}
						<CopyLinkButton command={`/link ${whatsAppLink.code}`} />
						<button
							type="button"
							disabled={checking !== null}
							onClick={() => {
								void checkConnection("whatsapp");
							}}
							className="flex shrink-0 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-[6px] border border-input bg-card px-3 py-1.5 text-[11.5px] font-semibold text-foreground disabled:cursor-default disabled:opacity-60"
						>
							{checking === "whatsapp" && (
								<Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
							)}
							{checking === "whatsapp" ? "Checking…" : "Check connection"}
						</button>
					</div>
				</div>
			)}
			{error && <p className="mt-3 text-[12px] text-destructive">{error}</p>}
		</section>
	);
}

function PasswordCard() {
	const [currentPassword, setCurrentPassword] = useState("");
	const [newPassword, setNewPassword] = useState("");
	const [confirmPassword, setConfirmPassword] = useState("");
	const [saving, setSaving] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [success, setSuccess] = useState<string | null>(null);

	const save = async () => {
		setError(null);
		setSuccess(null);
		if (newPassword.length < 8) {
			setError("The new password must contain at least 8 characters.");
			return;
		}
		if (newPassword !== confirmPassword) {
			setError("The new passwords do not match.");
			return;
		}
		setSaving(true);
		try {
			await usersApi.changePassword({
				currentPassword: currentPassword || null,
				newPassword,
			});
			setCurrentPassword("");
			setNewPassword("");
			setConfirmPassword("");
			setSuccess("Password updated.");
		} catch (caught: unknown) {
			setError(getApiErrorMessage(caught, "Could not update your password."));
		} finally {
			setSaving(false);
		}
	};

	return (
		<section className="rounded-[12px] border border-border bg-card p-5">
			<SectionHeading
				icon={<KeyRound className="size-4" />}
				title="Password"
				description="Use at least 8 characters. Google-only accounts can set a password here."
			/>
			<div className="grid gap-4 sm:grid-cols-2">
				<label className="sm:col-span-2">
					<span className={labelClass}>Current password</span>
					<input
						type="password"
						autoComplete="current-password"
						value={currentPassword}
						onChange={(event) => {
							setCurrentPassword(event.target.value);
						}}
						placeholder="Leave empty if you do not have one"
						className={inputClass}
					/>
				</label>
				<label>
					<span className={labelClass}>New password</span>
					<input
						type="password"
						autoComplete="new-password"
						value={newPassword}
						onChange={(event) => {
							setNewPassword(event.target.value);
						}}
						className={inputClass}
					/>
				</label>
				<label>
					<span className={labelClass}>Confirm password</span>
					<input
						type="password"
						autoComplete="new-password"
						value={confirmPassword}
						onChange={(event) => {
							setConfirmPassword(event.target.value);
						}}
						className={inputClass}
					/>
				</label>
			</div>
			<div className="mt-5 flex items-center justify-between">
				<Feedback error={error} success={success} />
				<button
					type="button"
					disabled={saving || !newPassword}
					onClick={() => {
						void save();
					}}
					className="ml-auto cursor-pointer rounded-[7px] border border-input bg-card px-4 py-2 text-[12.5px] font-semibold text-foreground transition-colors hover:border-border-hover disabled:cursor-default disabled:opacity-50"
				>
					{saving ? "Updating…" : "Update password"}
				</button>
			</div>
		</section>
	);
}

function TwoFactorCard({ user }: { user: CurrentUser }) {
	const setUser = useUserStore((state) => state.setUser);
	const [status, setStatus] = useState<usersApi.TwoFactorStatus>({
		enabled: user.twoFactorEnabled,
		backupCodesRemaining: 0,
	});
	const [setup, setSetup] = useState<usersApi.TwoFactorSetup | null>(null);
	const [backupCodes, setBackupCodes] = useState<string[] | null>(null);
	const [currentPassword, setCurrentPassword] = useState("");
	const [code, setCode] = useState("");
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		void usersApi
			.getTwoFactorStatus()
			.then(setStatus)
			.catch(() => {
				// The account data still provides a safe enabled/disabled fallback.
			});
	}, []);

	const beginSetup = async () => {
		setBusy(true);
		setError(null);
		try {
			setSetup(await usersApi.beginTwoFactorSetup(currentPassword || null));
			setCode("");
		} catch (caught: unknown) {
			setError(getApiErrorMessage(caught, "Could not start two-factor setup."));
		} finally {
			setBusy(false);
		}
	};

	const confirmSetup = async () => {
		if (!setup) return;
		setBusy(true);
		setError(null);
		try {
			const codes = await usersApi.confirmTwoFactorSetup(setup.setupToken, code);
			setBackupCodes(codes);
			setSetup(null);
			setStatus({ enabled: true, backupCodesRemaining: codes.length });
			setUser({ ...user, twoFactorEnabled: true });
			setCurrentPassword("");
			setCode("");
		} catch (caught: unknown) {
			setError(getApiErrorMessage(caught, "The authentication code is invalid."));
		} finally {
			setBusy(false);
		}
	};

	const disable = async () => {
		setBusy(true);
		setError(null);
		try {
			await usersApi.disableTwoFactor({
				currentPassword: currentPassword || null,
				code,
			});
			setStatus({ enabled: false, backupCodesRemaining: 0 });
			setUser({ ...user, twoFactorEnabled: false });
			setCurrentPassword("");
			setCode("");
		} catch (caught: unknown) {
			setError(getApiErrorMessage(caught, "Could not disable two-factor authentication."));
		} finally {
			setBusy(false);
		}
	};

	const regenerate = async () => {
		setBusy(true);
		setError(null);
		try {
			const codes = await usersApi.regenerateBackupCodes({
				currentPassword: currentPassword || null,
				code,
			});
			setBackupCodes(codes);
			setStatus({ enabled: true, backupCodesRemaining: codes.length });
			setCurrentPassword("");
			setCode("");
		} catch (caught: unknown) {
			setError(getApiErrorMessage(caught, "Could not regenerate backup codes."));
		} finally {
			setBusy(false);
		}
	};

	return (
		<section className="rounded-[12px] border border-border bg-card p-5">
			<SectionHeading
				icon={<ShieldCheck className="size-4" />}
				title="Two-factor authentication"
				description="Require a code from an authenticator app whenever you sign in."
			/>

			{backupCodes ? (
				<BackupCodes
					codes={backupCodes}
					onDone={() => {
						setBackupCodes(null);
					}}
				/>
			) : setup ? (
				<div className="grid gap-5 md:grid-cols-[180px_1fr]">
					<div className="flex items-center justify-center rounded-[10px] border border-input bg-white p-3">
						{/* The data URL is generated by the authenticated backend setup flow. */}
						{/* eslint-disable-next-line @next/next/no-img-element */}
						<img
							src={setup.qrCodeDataUrl}
							alt="QR code for your authenticator app"
							className="size-[156px]"
						/>
					</div>
					<div>
						<p className="text-[13px] font-semibold text-foreground">
							Scan this QR code
						</p>
						<p className="mt-1 text-[12px] leading-5 text-subtle dark:text-panel-body">
							Open your authenticator app, add an account, then enter the 6-digit
							code it shows.
						</p>
						<div className="mt-3 rounded-[7px] bg-hover px-3 py-2 dark:bg-white/5">
							<span className="block text-[9.5px] text-meta">
								Manual setup key
							</span>
							<code className="mt-1 block break-all font-mono text-[11.5px] text-foreground">
								{setup.secret}
							</code>
						</div>
						<label className="mt-3 block">
							<span className={labelClass}>Authentication code</span>
							<input
								inputMode="numeric"
								autoComplete="one-time-code"
								value={code}
								onChange={(event) => {
									setCode(event.target.value);
								}}
								maxLength={6}
								placeholder="000000"
								className={inputClass}
							/>
						</label>
						<div className="mt-3 flex gap-2">
							<button
								type="button"
								onClick={() => {
									setSetup(null);
									setCode("");
								}}
								className="cursor-pointer rounded-[7px] border border-input px-3 py-2 text-[12px] font-semibold"
							>
								Cancel
							</button>
							<button
								type="button"
								disabled={busy || code.length !== 6}
								onClick={() => {
									void confirmSetup();
								}}
								className="cursor-pointer rounded-[7px] bg-petrol px-4 py-2 text-[12px] font-semibold text-white disabled:opacity-50"
							>
								Verify and enable
							</button>
						</div>
					</div>
				</div>
			) : status.enabled ? (
				<div>
					<div className="mb-4 flex items-center justify-between rounded-[9px] border border-petrol/20 bg-[#F2F8F8] px-4 py-3 dark:bg-petrol/10">
						<div className="flex items-center gap-2.5">
							<span className="size-2 rounded-full bg-emerald-500" />
							<span className="text-[13px] font-semibold text-foreground">
								Two-factor authentication is enabled
							</span>
						</div>
						<span className="text-[10.5px] text-subtle">
							<span className="font-mono">{status.backupCodesRemaining}</span> backup codes
						</span>
					</div>
					<div className="grid gap-4 sm:grid-cols-2">
						<label>
							<span className={labelClass}>Current password</span>
							<input
								type="password"
								value={currentPassword}
								onChange={(event) => {
									setCurrentPassword(event.target.value);
								}}
								placeholder="If your account has one"
								className={inputClass}
							/>
						</label>
						<label>
							<span className={labelClass}>TOTP or backup code</span>
							<input
								value={code}
								onChange={(event) => {
									setCode(event.target.value);
								}}
								autoComplete="one-time-code"
								className={inputClass}
							/>
						</label>
					</div>
					<div className="mt-4 flex flex-wrap gap-2">
						<button
							type="button"
							disabled={busy || !code}
							onClick={() => {
								void regenerate();
							}}
							className="cursor-pointer rounded-[7px] border border-input px-3.5 py-2 text-[12px] font-semibold text-foreground disabled:opacity-50"
						>
							Regenerate backup codes
						</button>
						{user.twoFactorEnforced ? (
							<span className="self-center text-[11.5px] font-medium text-meta">
								Required by your workspace
							</span>
						) : (
							<button
								type="button"
								disabled={busy || !code}
								onClick={() => {
									void disable();
								}}
								className="cursor-pointer rounded-[7px] px-3.5 py-2 text-[12px] font-semibold text-destructive hover:bg-destructive/10 disabled:opacity-50"
							>
								Disable 2FA
							</button>
						)}
					</div>
				</div>
			) : (
				<div className="flex flex-col gap-4">
					<div className="rounded-[9px] border border-dashed border-input px-4 py-3 text-[12.5px] leading-5 text-subtle dark:text-panel-body">
						Use any TOTP-compatible app, such as 1Password, Google Authenticator,
						Authy, or Microsoft Authenticator.
					</div>
					<label className="max-w-sm">
						<span className={labelClass}>Current password</span>
						<input
							type="password"
							value={currentPassword}
							onChange={(event) => {
								setCurrentPassword(event.target.value);
							}}
							placeholder="If your account has one"
							className={inputClass}
						/>
					</label>
					<button
						type="button"
						disabled={busy}
						onClick={() => {
							void beginSetup();
						}}
						className="w-fit cursor-pointer rounded-[7px] bg-petrol px-4 py-2 text-[12.5px] font-semibold text-white disabled:opacity-50"
					>
						Set up authenticator app
					</button>
				</div>
			)}
			<Feedback error={error} success={null} />
		</section>
	);
}

function PreferencesCard() {
	const appName = useAppearanceStore((state) => state.appearance.appName);
	const confirmExternalLinks = useConfirmExternalLinks();
	const responseSoundEnabled = useResponseSoundEnabled();
	const showShortcutsInMenu = useShowShortcutsInMenu();

	return (
		<div className="flex flex-col gap-4">
			<section className="rounded-[12px] border border-border bg-card p-5">
				<SectionHeading
					icon={<Menu className="size-4" />}
					title="Navigation"
					description="Choose where workspace shortcuts appear."
				/>
				<div className="flex items-center justify-between gap-6 rounded-[9px] border border-input px-4 py-3.5">
					<div>
						<p className="text-[13px] font-semibold text-foreground">
							Show shortcuts in the sidebar
						</p>
						<p className="mt-0.5 text-[12px] leading-5 text-subtle dark:text-panel-body">
							On larger screens, workspace shortcuts appear directly in the
							sidebar instead of the overflow menu.
						</p>
					</div>
					<Switch
						checked={showShortcutsInMenu}
						onCheckedChange={setShowShortcutsInMenu}
						aria-label="Show shortcuts in the sidebar"
						className="cursor-pointer"
					/>
				</div>
			</section>
			<section className="rounded-[12px] border border-border bg-card p-5">
				<SectionHeading
					icon={<ShieldCheck className="size-4" />}
					title="External links"
					description="Choose whether links in assistant responses require confirmation."
				/>
				<div className="flex items-center justify-between gap-6 rounded-[9px] border border-input px-4 py-3.5">
					<div>
						<p className="text-[13px] font-semibold text-foreground">
							Confirm before opening external links
						</p>
						<p className="mt-0.5 text-[12px] leading-5 text-subtle dark:text-panel-body">
							Regular clicks show a safety confirmation. Ctrl/Cmd+click opens
							directly in a new tab. This preference is saved on this browser.
						</p>
					</div>
					<Switch
						checked={confirmExternalLinks}
						onCheckedChange={setConfirmExternalLinks}
						aria-label="Confirm before opening external links"
						className="cursor-pointer"
					/>
				</div>
			</section>
			<section className="rounded-[12px] border border-border bg-card p-5">
				<SectionHeading
					icon={<Volume2 className="size-4" />}
					title="Response sound"
					description={`Choose whether ${appName} plays a sound when an agent finishes responding.`}
				/>
				<div className="flex items-center justify-between gap-6 rounded-[9px] border border-input px-4 py-3.5">
					<div>
						<p className="text-[13px] font-semibold text-foreground">
							Play a sound when a response is ready
						</p>
						<p className="mt-0.5 text-[12px] leading-5 text-subtle dark:text-panel-body">
							This preference is saved on this browser.
						</p>
					</div>
					<Switch
						checked={responseSoundEnabled}
						onCheckedChange={setResponseSoundEnabled}
						aria-label="Play a sound when a response is ready"
						className="cursor-pointer"
					/>
				</div>
			</section>
		</div>
	);
}

export type ProfileSection =
	| "information"
	| "security"
	| "preferences"
	| "connected-accounts";

const sectionCopy: Record<
	ProfileSection,
	{ title: string; description: string }
> = {
	information: {
		title: "Information",
		description: "Manage your name, email, and profile photo.",
	},
	security: {
		title: "Security",
		description: "Manage your password and two-factor authentication.",
	},
	preferences: {
		title: "Preferences",
		description: "",
	},
	"connected-accounts": {
		title: "Connected accounts",
		description:
			"Link external identities so side-channel agents can apply your Auxilia permissions.",
	},
};

export default function ProfileSettings({
	user,
	section,
}: {
	user: CurrentUser;
	section: ProfileSection;
}) {
	const appName = useAppearanceStore((state) => state.appearance.appName);
	const copy =
		section === "preferences"
			? {
					...sectionCopy.preferences,
					description: `Choose how ${appName} behaves for you on this browser.`,
				}
			: sectionCopy[section];

	return (
		<div className="flex flex-col gap-4">
			<div className="mb-1">
				<span className="text-[10.5px] font-semibold text-subtle dark:text-panel-dim">
					{copy.title}
				</span>
				<p className="mt-1.5 max-w-[620px] text-[13px] leading-[1.55] text-subtle dark:text-panel-body">
					{copy.description}
				</p>
			</div>
			<div className={section === "information" ? "" : "hidden"}>
				<IdentityCard user={user} />
			</div>
			<div className={section === "security" ? "contents" : "hidden"}>
					<PasswordCard />
					<TwoFactorCard user={user} />
			</div>
			<div className={section === "preferences" ? "" : "hidden"}>
				<PreferencesCard />
			</div>
			<div className={section === "connected-accounts" ? "" : "hidden"}>
				<ConnectedAccountsCard />
			</div>
		</div>
	);
}
