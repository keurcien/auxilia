"use client";

import { useEffect, useState } from "react";
import { Check, Copy, Download, Loader2, ShieldCheck } from "lucide-react";
import { AuthShell } from "@/components/auth/auth-shell";
import { getApiErrorMessage } from "@/lib/api/errors";
import * as authApi from "@/lib/api/resources/auth";
import * as usersApi from "@/lib/api/resources/users";
import { useAppearanceStore } from "@/stores/appearance-store";
import { useUserStore } from "@/stores/user-store";
import type { CurrentUser } from "@/types/auth";

const inputClass =
	"w-full rounded-md border border-input bg-canvas px-4 py-3 text-[14px] font-medium text-ink outline-none transition-[border-color,box-shadow] placeholder:text-meta focus:border-petrol focus:shadow-[0_0_0_3px_rgba(22,96,110,0.10)]";

export default function RequiredTwoFactorSetupPage() {
	const setUser = useUserStore((state) => state.setUser);
	const logout = useUserStore((state) => state.logout);
	const appName = useAppearanceStore((state) => state.appearance.appName);
	const [user, setLocalUser] = useState<CurrentUser | null>(null);
	const [setup, setSetup] = useState<usersApi.TwoFactorSetup | null>(null);
	const [backupCodes, setBackupCodes] = useState<string[] | null>(null);
	const [currentPassword, setCurrentPassword] = useState("");
	const [code, setCode] = useState("");
	const [busy, setBusy] = useState(false);
	const [copied, setCopied] = useState(false);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		let active = true;
		void authApi
			.getCurrentUser()
			.then((currentUser) => {
				if (!currentUser.twoFactorRequired) {
					window.location.replace("/agents");
					return;
				}
				if (active) {
					setLocalUser(currentUser);
					setUser(currentUser);
				}
			})
			.catch(() => {
				window.location.replace("/auth");
			});
		return () => {
			active = false;
		};
	}, [setUser]);

	const beginSetup = async () => {
		setBusy(true);
		setError(null);
		try {
			setSetup(await usersApi.beginTwoFactorSetup(currentPassword || null));
			setCode("");
		} catch (caught: unknown) {
			setError(getApiErrorMessage(caught, "Could not start 2FA setup."));
		} finally {
			setBusy(false);
		}
	};

	const confirmSetup = async () => {
		if (!setup || !user) return;
		setBusy(true);
		setError(null);
		try {
			const codes = await usersApi.confirmTwoFactorSetup(setup.setupToken, code);
			const securedUser = {
				...user,
				twoFactorEnabled: true,
				twoFactorRequired: false,
			};
			setLocalUser(securedUser);
			setUser(securedUser);
			setBackupCodes(codes);
			setSetup(null);
			setCurrentPassword("");
			setCode("");
		} catch (caught: unknown) {
			setError(
				getApiErrorMessage(caught, "The authentication code is invalid."),
			);
		} finally {
			setBusy(false);
		}
	};

	const copyBackupCodes = async () => {
		if (!backupCodes) return;
		try {
			await navigator.clipboard.writeText(backupCodes.join("\n"));
			setCopied(true);
		} catch {
			setError("Could not copy the backup codes.");
		}
	};

	const downloadBackupCodes = () => {
		if (!backupCodes) return;
		const fileAppName =
			appName.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") ||
			"app";
		const content = [
			`${appName} backup codes`,
			"Each code can be used once.",
			"",
			...backupCodes,
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

	if (!user) {
		return (
			<div
				role="status"
				aria-label="Checking account security"
				className="flex min-h-svh items-center justify-center bg-background"
			>
				<Loader2 className="size-6 animate-spin text-petrol" aria-hidden="true" />
			</div>
		);
	}

	return (
		<AuthShell
			wide
			title="Secure your account"
			description="Your workspace requires two-factor authentication. Set up an authenticator app before continuing."
			footer={
				<button
					type="button"
					onClick={() => {
						void logout();
					}}
					className="cursor-pointer font-semibold text-petrol hover:underline"
				>
					Sign out
				</button>
			}
		>
			<div className="rounded-[12px] border border-border bg-card p-5">
				<div className="mb-5 flex items-start gap-3">
					<span className="flex size-9 shrink-0 items-center justify-center rounded-[9px] border border-input bg-hover text-petrol dark:bg-white/5 dark:text-panel-terminal">
						<ShieldCheck className="size-4" aria-hidden="true" />
					</span>
					<div>
						<h2 className="text-[14px] font-semibold text-foreground">
							Authenticator app
						</h2>
						<p className="mt-0.5 text-[12.5px] leading-5 text-subtle dark:text-panel-body">
							Use any TOTP-compatible app, such as 1Password, Google
							Authenticator, Authy, or Microsoft Authenticator.
						</p>
					</div>
				</div>

				{backupCodes ? (
					<div>
						<div className="rounded-[9px] border border-amber-300/70 bg-amber-50 px-4 py-3 text-[12.5px] leading-5 text-amber-950 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-100">
							Save these backup codes now. Each code can be used once if you
							lose access to your authenticator.
						</div>
						<div className="mt-4 grid grid-cols-2 gap-2 rounded-[9px] border border-input bg-hover p-4 font-mono text-[12.5px] text-foreground dark:bg-white/5">
							{backupCodes.map((backupCode) => (
								<code key={backupCode}>{backupCode}</code>
							))}
						</div>
						<div className="mt-4 flex flex-wrap items-center gap-2">
							<button
								type="button"
								onClick={downloadBackupCodes}
								className="flex shrink-0 cursor-pointer items-center gap-2 whitespace-nowrap rounded-[7px] border border-input px-3.5 py-2 text-[12px] font-semibold text-foreground hover:border-border-hover"
							>
								<Download className="size-3.5" aria-hidden="true" />
								Download codes
							</button>
							<button
								type="button"
								onClick={() => {
									void copyBackupCodes();
								}}
								className="flex shrink-0 cursor-pointer items-center gap-2 whitespace-nowrap rounded-[7px] border border-input px-3.5 py-2 text-[12px] font-semibold text-foreground hover:border-border-hover"
							>
								{copied ? (
									<Check className="size-3.5" aria-hidden="true" />
								) : (
									<Copy className="size-3.5" aria-hidden="true" />
								)}
								{copied ? "Copied" : "Copy codes"}
							</button>
							<button
								type="button"
								onClick={() => {
									window.location.assign("/agents");
								}}
								className="shrink-0 cursor-pointer whitespace-nowrap rounded-[7px] bg-petrol px-4 py-2 text-[12px] font-semibold text-white hover:opacity-90"
							>
								I saved my codes. Continue
							</button>
						</div>
					</div>
				) : setup ? (
					<div className="grid gap-5 md:grid-cols-[180px_1fr]">
						<div className="flex items-center justify-center rounded-[10px] border border-input bg-white p-3">
							{/* The authenticated backend generated this short-lived data URL. */}
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
								Add the account in your authenticator, then enter its 6-digit
								code.
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
								<span className="mb-1.5 block text-[10.5px] font-semibold text-label">
									Authentication code
								</span>
								<input
									inputMode="numeric"
									autoComplete="one-time-code"
									autoFocus
									value={code}
									onChange={(event) => {
										setCode(event.target.value);
									}}
									maxLength={6}
									placeholder="000000"
									className={inputClass}
								/>
							</label>
							<button
								type="button"
								disabled={busy || code.length !== 6}
								onClick={() => {
									void confirmSetup();
								}}
								className="mt-3 flex cursor-pointer items-center gap-2 rounded-[7px] bg-petrol px-4 py-2.5 text-[12.5px] font-semibold text-white disabled:cursor-default disabled:opacity-50"
							>
								{busy && (
									<Loader2
										className="size-3.5 animate-spin"
										aria-hidden="true"
									/>
								)}
								Verify and enable 2FA
							</button>
						</div>
					</div>
				) : (
					<div>
						<label className="block max-w-sm">
							<span className="mb-1.5 block text-[10.5px] font-semibold text-label">
								Current password
							</span>
							<input
								type="password"
								autoComplete="current-password"
								value={currentPassword}
								onChange={(event) => {
									setCurrentPassword(event.target.value);
								}}
								placeholder="Leave blank for OAuth-only accounts"
								className={inputClass}
							/>
						</label>
						<button
							type="button"
							disabled={busy}
							onClick={() => {
								void beginSetup();
							}}
							className="mt-4 flex cursor-pointer items-center gap-2 rounded-[7px] bg-petrol px-4 py-2.5 text-[12.5px] font-semibold text-white disabled:cursor-default disabled:opacity-50"
						>
							{busy && (
								<Loader2
									className="size-3.5 animate-spin"
									aria-hidden="true"
								/>
							)}
							Set up authenticator app
						</button>
					</div>
				)}

				{error && (
					<p role="alert" className="mt-4 text-[12px] font-medium text-destructive">
						{error}
					</p>
				)}
			</div>
		</AuthShell>
	);
}
