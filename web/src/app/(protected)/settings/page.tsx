"use client";

import { useCallback, useEffect, useState } from "react";
import { Copy, Check, KeyRound, Plus, Trash2 } from "lucide-react";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import { useConfirmDialog } from "@/components/providers/dialog-provider";
import CreateTokenDialog, { type PersonalAccessToken } from "./create-token-dialog";
import WorkspaceModels from "./workspace-models";
import WorkspaceSandboxes from "./workspace-sandboxes";
import InstanceAppearanceSettings from "./workspace-appearance";
import WorkspaceAuthentication from "./workspace-authentication";
import WorkspaceNotifications from "./workspace-notifications";
import WorkspaceObservability from "./workspace-observability";
import ProfileSettings, { type ProfileSection } from "./profile-settings";
import { SubpageHeader } from "@/components/layout/subpage-header";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import * as authApi from "@/lib/api/resources/auth";
import { useQueryParamState } from "@/hooks/use-query-param-state";
import { useUserStore } from "@/stores/user-store";

function formatDate(dateStr: string): string {
	return new Date(dateStr)
		.toLocaleDateString("en-US", {
			year: "numeric",
			month: "short",
			day: "numeric",
		})
		.toLowerCase();
}

/** One-time reveal of a freshly created token (design 18a banner). */
function TokenRevealBanner({ plaintext }: { plaintext: string }) {
	const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">(
		"idle",
	);
	const copied = copyState === "copied";

	const handleCopy = () => {
		// navigator.clipboard is absent on insecure origins (self-hosted over
		// plain HTTP) even though the DOM types claim otherwise — widen the
		// type so the guard survives type-aware lint, and the click can't
		// throw before the fallback.
		const clipboard = navigator.clipboard as Clipboard | undefined;
		if (!clipboard) {
			setCopyState("failed");
			return;
		}
		clipboard
			.writeText(plaintext)
			.then(() => {
				setCopyState("copied");
				setTimeout(() => {
					setCopyState("idle");
				}, 2000);
			})
			.catch(() => {
				// Clipboard permission denied — the token is visible in the
				// banner, so point the user at manual selection.
				setCopyState("failed");
			});
	};

	return (
		<div className="mb-3 flex items-center gap-3 rounded-[10px] border border-sparkline bg-[#F2F8F8] px-4 py-[13px] dark:border-petrol/40 dark:bg-petrol/10">
			<span className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-[#DCE9EB] bg-white text-petrol dark:border-white/10 dark:bg-white/10 dark:text-panel-terminal">
				<KeyRound className="size-[15px]" />
			</span>
			<span className="min-w-0 flex-1">
				<span className="block text-[13px] font-semibold text-foreground">
					Copy your new token now, you won&apos;t be able to see it again.
				</span>
				<span className="mt-[3px] block truncate font-mono text-[12px] text-petrol dark:text-panel-terminal">
					{plaintext}
				</span>
				{copyState === "failed" && (
					<span className="mt-1 block text-[11.5px] font-medium text-destructive">
						Copying failed, select the token above and copy it manually.
					</span>
				)}
			</span>
			<button
				type="button"
				onClick={handleCopy}
				className="inline-flex shrink-0 cursor-pointer items-center gap-1.5 rounded-[7px] bg-petrol px-3.5 py-[7px] text-[12.5px] font-semibold text-white transition-opacity hover:opacity-90"
			>
				{copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
				{copied ? "Copied!" : "Copy"}
			</button>
		</div>
	);
}

type SettingsTab =
	| "profile"
	| "appearance"
	| "authentication"
	| "notifications"
	| "observability"
	| "models"
	| "sandboxes";

function isAdminSettingsTab(
	tab: string,
): tab is Exclude<SettingsTab, "profile"> {
	return (
		tab === "appearance" ||
		tab === "authentication" ||
		tab === "notifications" ||
		tab === "observability" ||
		tab === "models" ||
		tab === "sandboxes"
	);
}

type ProfilePageSection = ProfileSection | "tokens";

function isProfileSection(value: string): value is ProfilePageSection {
	return (
		value === "information" ||
		value === "security" ||
		value === "preferences" ||
		value === "tokens"
	);
}

export default function SettingsPage() {
	const confirmDialog = useConfirmDialog();
	const [tokens, setTokens] = useState<PersonalAccessToken[]>([]);
	const [isLoading, setIsLoading] = useState(true);
	const [revealedToken, setRevealedToken] = useState<string | null>(null);
	const [modelCount, setModelCount] = useState<number | null>(null);
	const [sandboxCount, setSandboxCount] = useState<number | null>(null);
	const [errorDialogOpen, setErrorDialogOpen] = useState(false);
	const [createDialogOpen, setCreateDialogOpen] = useState(false);
	const user = useUserStore((state) => state.user);
	const fetchUser = useUserStore((state) => state.fetchUser);
	const isAdmin = user?.role === "admin";
	const handleForbidden = useCallback(() => {
		setErrorDialogOpen(true);
	}, []);

	const [tabParam, setTab] = useQueryParamState("tab", "appearance");
	const [profileSectionParam, setProfileSection] = useQueryParamState(
		"section",
		"information",
	);
	const profileSection: ProfilePageSection =
		tabParam === "tokens"
			? "tokens"
			: isProfileSection(profileSectionParam)
				? profileSectionParam
				: "information";
	const tab: SettingsTab =
		tabParam === "profile" || tabParam === "tokens"
			? "profile"
			: isAdmin && isAdminSettingsTab(tabParam)
				? tabParam
				: isAdmin
					? "appearance"
					: "profile";

	useEffect(() => {
		void fetchUser();
	}, [fetchUser]);

	// The token routes are admin-only — fetching as a member would just 403.
	useEffect(() => {
		if (!isAdmin) return;
		const fetchTokens = async () => {
			try {
				setTokens(await authApi.listTokens());
			} catch (error: unknown) {
				if (
					error instanceof Object &&
					"status" in error &&
					error.status === 403
				) {
					setErrorDialogOpen(true);
				} else {
					console.error("Error fetching tokens:", error);
				}
			} finally {
				setIsLoading(false);
			}
		};
		void fetchTokens();
	}, [isAdmin]);

	const handleDelete = async (token: PersonalAccessToken) => {
		const confirmed = await confirmDialog({
			title: `Revoke “${token.name}”?`,
			description:
				"Any services using this token will immediately lose access.",
			confirmLabel: "Revoke token",
			destructive: true,
		});
		if (!confirmed) return;

		try {
			await authApi.deleteToken(token.id);
			setTokens((prev) => prev.filter((t) => t.id !== token.id));
		} catch (error: unknown) {
			if (
				error instanceof Object &&
				"status" in error &&
				error.status === 403
			) {
				setErrorDialogOpen(true);
			} else {
				console.error("Error deleting token:", error);
			}
		}
	};

	const tokenColumns: DataTableColumn<PersonalAccessToken>[] = [
		{
			key: "token",
			header: "Token",
			width: "minmax(0, 1fr)",
			cell: (token) => (
				<div className="min-w-0">
					<span className="block truncate text-[13.5px] font-semibold text-foreground">
						{token.name}
					</span>
					<span className="mt-0.5 block truncate font-mono text-[10.5px] text-meta dark:text-panel-dim">
						{token.prefix}…
					</span>
				</div>
			),
		},
		{
			key: "created",
			header: "Created",
			width: "160px",
			mobileWidth: "auto",
			cell: (token) => (
				<span className="font-mono text-[11px] text-subtle dark:text-muted-foreground">
					{formatDate(token.createdAt)}
				</span>
			),
		},
		{
			key: "actions",
			header: "",
			width: "40px",
			cell: (token) => (
				<button
					type="button"
					title="Revoke token"
					aria-label={`Revoke ${token.name}`}
					onClick={() => {
						void handleDelete(token);
					}}
					className="flex size-7 cursor-pointer items-center justify-center rounded-[7px] text-meta transition-colors hover:bg-[#FBEFED] hover:text-[#B04A3A] dark:hover:bg-rose-950"
				>
					<Trash2 className="size-3.5" />
				</button>
			),
		},
	];

	const railTabClass = (active: boolean) =>
		`flex cursor-pointer items-center gap-2 border-l-2 px-3 py-[7px] text-left text-[13px] transition-colors ${
			active
				? "border-petrol font-semibold text-foreground"
				: "border-transparent font-medium text-subtle hover:text-foreground dark:text-panel-body"
		}`;

	return (
		<div className="flex h-svh min-w-0 flex-1 flex-col bg-background animate-in fade-in duration-300">
			<SubpageHeader
				trail={
					tab === "profile"
						? [
								{ label: "workspace" },
								{ label: "profile" },
								{ label: profileSection },
							]
						: [{ label: "workspace" }, { label: "settings" }]
				}
			/>

			<ForbiddenErrorDialog
				open={errorDialogOpen}
				onOpenChange={setErrorDialogOpen}
				title="Insufficient privileges"
				message="You are not allowed to perform this action."
			/>
			<CreateTokenDialog
				open={createDialogOpen}
				onOpenChange={setCreateDialogOpen}
				onTokenCreated={(token, plaintext) => {
					setTokens((prev) => [token, ...prev]);
					setRevealedToken(plaintext);
				}}
			/>

			<div className="flex min-h-0 flex-1">
				{/* Left rail: title + vertical section tabs */}
				<div className="w-[200px] flex-none pl-7 pt-8">
					<h1 className="mb-[18px] pl-3.5 font-display text-[22px] font-bold tracking-[-0.03em] text-foreground">
						{tab === "profile" ? "Profile" : "Settings"}
					</h1>
					{tab === "profile" ? (
						<div className="flex flex-col">
							<div className="mb-5">
								<p className="mb-1.5 px-3.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-meta dark:text-panel-dim">
									Account
								</p>
								<button
									type="button"
									className={railTabClass(profileSection === "information")}
									onClick={() => {
										setProfileSection("information");
									}}
								>
									Information
								</button>
								<button
									type="button"
									className={railTabClass(profileSection === "security")}
									onClick={() => {
										setProfileSection("security");
									}}
								>
									Security
								</button>
								<button
									type="button"
									className={railTabClass(profileSection === "preferences")}
									onClick={() => {
										setProfileSection("preferences");
									}}
								>
									Preferences
								</button>
							</div>
							<div>
								<p className="mb-1.5 px-3.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-meta dark:text-panel-dim">
									Developer
								</p>
								<button
									type="button"
									className={railTabClass(profileSection === "tokens")}
									onClick={() => {
										setProfileSection("tokens");
									}}
								>
									Access tokens
									{isAdmin && (
										<span className="font-mono text-[10.5px] font-normal text-meta dark:text-panel-dim">
											{tokens.length}
										</span>
									)}
								</button>
							</div>
						</div>
					) : (
						<div className="flex flex-col">
						{isAdmin && (
							<div className="mb-5">
								<p className="mb-1.5 px-3.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-meta dark:text-panel-dim">
									General
								</p>
								<button
									type="button"
									className={railTabClass(tab === "models")}
									onClick={() => {
										setTab("models");
									}}
								>
									Models
									{modelCount !== null && (
										<span className="font-mono text-[10.5px] font-normal text-meta dark:text-panel-dim">
											{modelCount}
										</span>
									)}
								</button>
							</div>
						)}
						{isAdmin && (
							<div className="mb-5">
								<p className="mb-1.5 px-3.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-meta dark:text-panel-dim">
									Integrations
								</p>
								<button
									type="button"
									className={railTabClass(tab === "authentication")}
									onClick={() => {
										setTab("authentication");
									}}
								>
									Authentication
								</button>
								<button
									type="button"
									className={railTabClass(tab === "notifications")}
									onClick={() => {
										setTab("notifications");
									}}
								>
									Notifications
								</button>
								<button
									type="button"
									className={railTabClass(tab === "observability")}
									onClick={() => {
										setTab("observability");
									}}
								>
									Observability
								</button>
								<button
									type="button"
									className={railTabClass(tab === "sandboxes")}
									onClick={() => {
										setTab("sandboxes");
									}}
								>
									Sandboxes
									{sandboxCount !== null && (
										<span className="font-mono text-[10.5px] font-normal text-meta dark:text-panel-dim">
											{sandboxCount}
										</span>
									)}
								</button>
							</div>
						)}
						{isAdmin && (
							<div className="mb-5">
								<p className="mb-1.5 px-3.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-meta dark:text-panel-dim">
									Server
								</p>
								<button
									type="button"
									className={railTabClass(tab === "appearance")}
									onClick={() => {
										setTab("appearance");
									}}
								>
									Appearance
								</button>
							</div>
						)}
						</div>
					)}
				</div>

				{/* Content */}
				<div className="min-w-0 flex-1 overflow-y-auto px-9 py-8 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
					<div className="mx-auto max-w-[800px]">
						<section
							className={
								tab === "profile" && profileSection !== "tokens"
									? ""
									: "hidden"
							}
						>
							{profileSection !== "tokens" &&
								(user ? (
									<ProfileSettings user={user} section={profileSection} />
								) : (
									<div className="h-40 animate-pulse rounded-[12px] border border-border bg-card" />
								))}
						</section>

						{isAdmin && (
							<section className={tab === "appearance" ? "" : "hidden"}>
								<InstanceAppearanceSettings
									onForbidden={() => {
										setErrorDialogOpen(true);
									}}
								/>
							</section>
						)}

						{isAdmin && (
							<section className={tab === "authentication" ? "" : "hidden"}>
								<WorkspaceAuthentication
									onForbidden={handleForbidden}
								/>
							</section>
						)}

						{isAdmin && (
							<section className={tab === "notifications" ? "" : "hidden"}>
								<WorkspaceNotifications
									onForbidden={handleForbidden}
								/>
							</section>
						)}

						{isAdmin && (
							<section className={tab === "observability" ? "" : "hidden"}>
								<WorkspaceObservability
									onForbidden={handleForbidden}
								/>
							</section>
						)}

						{/* Access tokens — kept mounted so the profile count stays live */}
						<section
							className={
								tab === "profile" && profileSection === "tokens"
									? ""
									: "hidden"
							}
						>
							<div className="mb-1.5 flex items-baseline gap-2.5">
								<span className="text-[10.5px] font-semibold text-subtle dark:text-panel-dim">
									Personal access tokens
								</span>
								<span className="flex-1" />
								{isAdmin && (
									<button
										type="button"
										onClick={() => {
											setCreateDialogOpen(true);
										}}
										className="flex cursor-pointer items-center gap-1.5 rounded-[7px] bg-primary px-4 py-2 text-[12.5px] font-semibold text-primary-foreground transition-opacity hover:opacity-90"
									>
										<Plus className="size-3.5" />
										Generate token
									</button>
								)}
							</div>
							<p className="mb-3.5 max-w-[620px] text-[13px] leading-[1.55] text-subtle dark:text-panel-body">
								Authenticate external services against the API, n8n, the
								invoke endpoint, scripts. Tokens act as you.
							</p>

							{revealedToken && <TokenRevealBanner plaintext={revealedToken} />}

							{isAdmin ? (
								<DataTable
									columns={tokenColumns}
									rows={tokens}
									rowKey={(token) => token.id}
									isLoading={isLoading}
									emptyMessage={
										<span>
											No personal access tokens yet.
											<br />
											<span className="text-[13px] font-normal">
												Generate a token to authenticate external services.
											</span>
										</span>
									}
								/>
							) : (
								<div className="rounded-[10px] border border-dashed border-input px-5 py-8 text-center text-[13px] font-medium text-meta dark:border-white/15 dark:text-panel-dim">
									Personal access tokens are managed by workspace admins.
								</div>
							)}
						</section>

						{/* Workspace models — admin only */}
						{isAdmin && (
							<section className={tab === "models" ? "" : "hidden"}>
								<WorkspaceModels
									onForbidden={() => {
										setErrorDialogOpen(true);
									}}
									onCountChange={setModelCount}
								/>
							</section>
						)}

						{/* Workspace sandboxes — admin only */}
						{isAdmin && (
							<section className={tab === "sandboxes" ? "" : "hidden"}>
								<WorkspaceSandboxes
									onForbidden={() => {
										setErrorDialogOpen(true);
									}}
									onCountChange={setSandboxCount}
								/>
							</section>
						)}
					</div>
				</div>
			</div>
		</div>
	);
}
