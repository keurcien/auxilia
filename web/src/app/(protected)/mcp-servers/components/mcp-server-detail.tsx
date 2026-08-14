"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Eye, EyeOff } from "lucide-react";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import { SageAlert } from "@/components/ui/sage-alert";
import { SageDropdownMenu } from "@/components/ui/sage-dropdown-menu";
import { api } from "@/lib/api/client";
import { getApiErrorMessage } from "@/lib/api/errors";
import { useMcpServersStore } from "@/stores/mcp-servers-store";
import { useUserStore } from "@/stores/user-store";
import {
	MCPServer,
	MCPServerUpdate,
	OAuthSecretHint,
} from "@/types/mcp-servers";
import { AuthTypeBadge } from "./auth-type-badge";
import { ConnectedUsersPanel } from "./connected-users-panel";
import { ConnectionTestBanner } from "./connection-test-banner";
import { ServerIconTile } from "./server-icon-tile";
import {
	HeaderButton,
	HeaderPrimaryButton,
	SubpageHeader,
} from "@/components/layout/subpage-header";
import { isOfficialIcon, slugify } from "../lib/constants";
import { useConnectionTest } from "../lib/use-connection-test";

const AUTH_TYPE_LABELS: Record<MCPServer["authType"], string> = {
	none: "None",
	api_key: "API key",
	oauth2: "OAuth 2.0",
};

const LABEL_CLASS = "text-[13px] font-semibold text-foreground";
const INPUT_CLASS =
	"w-full rounded-lg border border-input bg-card px-3 py-[9px] text-[13.5px] font-medium text-foreground outline-none transition-[border-color,box-shadow] placeholder:text-meta dark:placeholder:text-panel-dim focus:border-petrol focus:shadow-[0_0_0_3px_rgba(22,96,110,0.10)]";
const MONO_INPUT_CLASS = `${INPUT_CLASS} font-mono text-[12.5px] font-normal`;

interface EditFormValues {
	name: string;
	url: string;
	iconUrl: string;
	description: string;
	apiKey: string;
	oauthClientId: string;
	oauthClientSecret: string;
}

function formFromServer(server: MCPServer): EditFormValues {
	return {
		name: server.name,
		url: server.url,
		iconUrl: server.iconUrl ?? "",
		description: server.description ?? "",
		apiKey: "",
		// client_id is a public identifier — prefill it so it's editable; the
		// secret is write-only and stays blank ("leave blank to keep").
		oauthClientId: server.oauthClientId ?? "",
		oauthClientSecret: "",
	};
}

/** Label/value row of the CONFIGURATION block (view mode). */
function ConfigRow({
	label,
	children,
	last = false,
}: {
	label: string;
	children: React.ReactNode;
	last?: boolean;
}) {
	return (
		<div
			className={`flex flex-col gap-1 py-[13px] sm:flex-row sm:items-baseline sm:gap-4 ${
				last ? "" : "border-b border-hairline dark:border-white/5"
			}`}
		>
			<span className="w-[200px] flex-none text-[13px] font-semibold text-body dark:text-panel-body">
				{label}
			</span>
			<span className="min-w-0">{children}</span>
		</div>
	);
}

interface MCPServerDetailProps {
	server: MCPServer;
	initialEdit: boolean;
}

export default function MCPServerDetail({
	server: initialServer,
	initialEdit,
}: MCPServerDetailProps) {
	const router = useRouter();
	const user = useUserStore((state) => state.user);
	const isAdmin = user?.role === "admin";
	const { updateMcpServer, deleteMcpServer, resetMcpServerConnections } =
		useMcpServersStore();

	const [server, setServer] = useState<MCPServer>(initialServer);
	const [isEditing, setIsEditing] = useState(initialEdit);
	// ?edit=1 must not expose the editor to non-admins — the backend would
	// 403 the save, but the destructive controls shouldn't render at all.
	const editing = isEditing && isAdmin;
	const [form, setForm] = useState<EditFormValues>(formFromServer(initialServer));
	const [fieldErrors, setFieldErrors] = useState<
		Partial<Record<keyof EditFormValues, string>>
	>({});
	const [submitError, setSubmitError] = useState<string | null>(null);
	const [isSubmitting, setIsSubmitting] = useState(false);
	const [isResetting, setIsResetting] = useState(false);
	const [forbiddenOpen, setForbiddenOpen] = useState(false);
	const [showSecret, setShowSecret] = useState(false);
	// Whether the saved server already has a static client secret; the secret
	// itself is never returned by the API.
	const [hasStoredSecret, setHasStoredSecret] = useState(
		!!initialServer.oauthClientId,
	);
	// Admin-only, non-reversible hint (last 4 + length) about the stored secret.
	const [secretHint, setSecretHint] = useState<OAuthSecretHint | null>(null);
	// Don't let the async hint fetch clobber a Client ID the admin is editing.
	const clientIdDirtyRef = useRef(false);

	const {
		status: testStatus,
		message: testMessage,
		reset: resetTest,
		runSavedTest,
		runCandidateTest,
	} = useConnectionTest();

	// Admin-only secret hint for OAuth servers (403 for non-admins is expected).
	useEffect(() => {
		if (server.authType !== "oauth2") return;
		const controller = new AbortController();
		void (async () => {
			try {
				const res = await api.get<OAuthSecretHint>(
					`/mcp-servers/${server.id}/oauth-secret-hint`,
					{ signal: controller.signal },
				);
				setSecretHint(res.data);
				if (res.data.isSet) setHasStoredSecret(true);
			} catch {
				// Aborted, non-admin, or no hint — leave the generic mask.
			}
		})();
		return () => {
			controller.abort();
		};
	}, [server.id, server.authType]);

	// Keep ?edit=1 in sync so a refresh restores the mode (shallow rewrite).
	const setMode = (editing: boolean) => {
		setIsEditing(editing);
		const url = new URL(window.location.href);
		if (editing) url.searchParams.set("edit", "1");
		else url.searchParams.delete("edit");
		window.history.replaceState(null, "", url);
	};

	const startEdit = () => {
		setForm(formFromServer(server));
		setFieldErrors({});
		setSubmitError(null);
		setShowSecret(false);
		clientIdDirtyRef.current = false;
		resetTest();
		setMode(true);
	};

	const cancelEdit = () => {
		setFieldErrors({});
		setSubmitError(null);
		resetTest();
		setMode(false);
	};

	const handleFormChange = (field: keyof EditFormValues, value: string) => {
		setForm((prev) => ({ ...prev, [field]: value }));
		if (field === "oauthClientId") clientIdDirtyRef.current = true;
		// Editing a field clears its error (rebuild without the key — no
		// dynamic access/delete, which static analysis flags as injection).
		setFieldErrors(
			(prev) =>
				Object.fromEntries(
					Object.entries(prev).filter(([key]) => key !== field),
				) as typeof fieldErrors,
		);
		// A prior test result no longer reflects the edited config.
		if (testStatus !== "idle") resetTest();
	};

	const handleTest = () => {
		// OAuth is per-user and interactive, so it's tested against the saved
		// server. An api_key edit with a blank field means "keep the stored
		// key", which likewise requires the saved config; everything else tests
		// the current form values without saving.
		const useSavedTest =
			!editing ||
			server.authType === "oauth2" ||
			(server.authType === "api_key" && !form.apiKey.trim());
		if (useSavedTest) {
			void runSavedTest(server);
		} else {
			void runCandidateTest({
				url: form.url,
				authType: server.authType,
				apiKey: form.apiKey,
			});
		}
	};

	const handleSave = async () => {
		const errors: typeof fieldErrors = {};
		if (!form.name.trim()) errors.name = "Name is required.";
		if (!form.url.trim()) errors.url = "Server address is required.";
		// Setting static OAuth credentials on a server without them requires
		// both fields — one alone would be silently dropped by the backend.
		if (server.authType === "oauth2" && !hasStoredSecret) {
			const id = form.oauthClientId.trim();
			const secret = form.oauthClientSecret.trim();
			if (id && !secret) {
				errors.oauthClientSecret =
					"Client secret is required when providing a Client ID.";
			} else if (secret && !id) {
				errors.oauthClientId =
					"Client ID is required when providing a client secret.";
			}
		}
		setFieldErrors(errors);
		if (Object.keys(errors).length > 0) return;

		setSubmitError(null);
		setIsSubmitting(true);
		try {
			const payload: MCPServerUpdate = {
				name: form.name,
				url: form.url,
				// Explicit null clears the stored value — undefined would be
				// dropped from the PATCH and silently keep the old one.
				description: form.description.trim() ? form.description : null,
				iconUrl: form.iconUrl.trim() ? form.iconUrl : null,
				// Credentials are sent only when the field was filled in; a blank
				// field keeps the stored secret untouched.
				apiKey:
					server.authType === "api_key" && form.apiKey ? form.apiKey : undefined,
				oauthClientId:
					server.authType === "oauth2" && form.oauthClientId
						? form.oauthClientId
						: undefined,
				oauthClientSecret:
					server.authType === "oauth2" && form.oauthClientSecret
						? form.oauthClientSecret
						: undefined,
			};
			const updated = await updateMcpServer(server.id, payload);
			setServer(updated);
			if (server.authType === "oauth2" && form.oauthClientSecret) {
				setHasStoredSecret(true);
				setSecretHint(null); // stale — the stored secret just changed
			}
			setMode(false);
		} catch (error: unknown) {
			if (error instanceof Object && "status" in error && error.status === 403) {
				setForbiddenOpen(true);
			} else {
				setSubmitError(getApiErrorMessage(error, "Failed to update MCP server."));
			}
		} finally {
			setIsSubmitting(false);
		}
	};

	const handleDelete = async () => {
		if (
			!window.confirm(
				`Delete "${server.name}"? Agents lose its tools immediately.`,
			)
		)
			return;
		setSubmitError(null);
		setIsSubmitting(true);
		try {
			await deleteMcpServer(server.id);
			router.push("/mcp-servers");
		} catch (error: unknown) {
			if (error instanceof Object && "status" in error && error.status === 403) {
				setForbiddenOpen(true);
			} else {
				setSubmitError(getApiErrorMessage(error, "Failed to delete MCP server."));
			}
			setIsSubmitting(false);
		}
	};

	// Shared by the header ⋮ menu, the edit footer, and the connected-users
	// panel ("Reset all connections"). Returns true when the reset ran.
	const handleReset = async (): Promise<boolean> => {
		if (
			!window.confirm(
				"This will revoke all user connections to this MCP server. Users will need to re-authenticate. Continue?",
			)
		)
			return false;
		setSubmitError(null);
		setIsResetting(true);
		try {
			await resetMcpServerConnections(server.id);
			return true;
		} catch (error: unknown) {
			if (error instanceof Object && "status" in error && error.status === 403) {
				setForbiddenOpen(true);
			} else {
				setSubmitError(
					getApiErrorMessage(error, "Failed to reset MCP server connections."),
				);
			}
			return false;
		} finally {
			setIsResetting(false);
		}
	};

	// Masked hint for the stored client secret: bullets for the hidden portion
	// plus the revealed suffix (when any), so the mask always spans the
	// secret's full length. Falls back to a generic mask without the hint.
	let secretMask: string | null = null;
	if (secretHint?.isSet) {
		const suffix = secretHint.last4 ?? "";
		const bulletCount = Math.max(0, (secretHint.length ?? 0) - suffix.length);
		secretMask = "•".repeat(bulletCount) + suffix || "••••••••";
	} else if (hasStoredSecret) {
		secretMask = "••••••••";
	}

	const isOauth = server.authType === "oauth2";
	const busy = isSubmitting || isResetting;

	return (
		<div className="flex h-svh min-w-0 flex-1 flex-col bg-background animate-in fade-in duration-300">
			<SubpageHeader
				trail={[
					{ label: "workspace" },
					{ label: "mcp-servers", href: "/mcp-servers" },
					{ label: slugify(server.name) },
				]}
			>
				<HeaderButton
					accent
					disabled={testStatus === "testing" || busy}
					onClick={handleTest}
				>
					{testStatus === "testing" ? "Testing…" : "Test connection"}
				</HeaderButton>
				{editing ? (
					<>
						<HeaderButton disabled={busy} onClick={cancelEdit}>
							Cancel
						</HeaderButton>
						<HeaderPrimaryButton
							disabled={busy}
							onClick={() => {
								void handleSave();
							}}
						>
							{isSubmitting ? "Saving…" : "Save changes"}
						</HeaderPrimaryButton>
					</>
				) : (
					isAdmin && (
						<>
							<HeaderButton onClick={startEdit}>Edit server</HeaderButton>
							<SageDropdownMenu
								items={[
									...(isOauth
										? [
												{
													label: "Reset connections",
													onClick: () => {
														void handleReset();
													},
												},
											]
										: []),
									{
										label: "Delete server",
										destructive: true,
										onClick: () => {
											void handleDelete();
										},
									},
								]}
							/>
						</>
					)
				)}
			</SubpageHeader>

			<div className="flex min-h-0 flex-1 flex-col md:flex-row">
				{/* Left panel — identity + configuration */}
				<div className="min-w-0 overflow-y-auto border-b border-border bg-background p-7 pb-11 md:flex-[1.05] md:border-b-0 md:border-r [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
					<div className="flex items-center gap-4">
						<ServerIconTile
							iconUrl={editing ? form.iconUrl || null : server.iconUrl}
							name={server.name}
							size={52}
						/>
						<div className="min-w-0 flex-1">
							<div className="flex flex-wrap items-center gap-2.5">
								<h1 className="font-display text-[26px] font-bold tracking-[-0.03em] text-foreground">
									{server.name}
								</h1>
								<AuthTypeBadge authType={server.authType} />
								{isOfficialIcon(server.iconUrl) && (
									<span className="rounded-full bg-hover px-[9px] py-[3px] text-[11px] font-semibold text-subtle dark:bg-white/10 dark:text-panel-body">
										Official
									</span>
								)}
							</div>
							<div className="mt-1 truncate font-mono text-[11.5px] text-meta dark:text-panel-dim">
								{server.url}
							</div>
						</div>
					</div>

					{(testStatus !== "idle" || submitError) && (
						<div className="mt-5 flex flex-col gap-2.5">
							<ConnectionTestBanner status={testStatus} message={testMessage} />
							{submitError && (
								<SageAlert key={submitError} variant="error" message={submitError} />
							)}
						</div>
					)}

					<div className="mb-1.5 mt-[30px]">
						<span className="font-mono text-[10.5px] font-semibold tracking-[0.09em] text-subtle dark:text-panel-dim">
							CONFIGURATION
						</span>
					</div>

					{!editing ? (
						<div>
							<ConfigRow label="Name">
								<span className="text-[13.5px] text-foreground">{server.name}</span>
							</ConfigRow>
							<ConfigRow label="Remote server address">
								<span className="break-all font-mono text-[12px] text-foreground">
									{server.url}
								</span>
							</ConfigRow>
							<ConfigRow label="Icon URL">
								{server.iconUrl ? (
									<span className="break-all font-mono text-[12px] text-foreground">
										{server.iconUrl}
									</span>
								) : (
									<span className="text-[13.5px] text-meta dark:text-panel-dim">—</span>
								)}
							</ConfigRow>
							<ConfigRow label="Description">
								{server.description ? (
									<span className="text-[13.5px] leading-[1.55] text-foreground">
										{server.description}
									</span>
								) : (
									<span className="text-[13.5px] text-meta dark:text-panel-dim">—</span>
								)}
							</ConfigRow>
							<ConfigRow
								label="Authentication method"
								last={server.authType === "none"}
							>
								<span className="text-[13.5px] text-foreground">
									{AUTH_TYPE_LABELS[server.authType]}
								</span>
							</ConfigRow>
							{server.authType === "api_key" && (
								<ConfigRow label="API key" last>
									<span className="inline-flex items-center gap-2.5">
										<span className="font-mono text-[12px] tracking-[0.08em] text-subtle dark:text-panel-dim">
											••••••••
										</span>
										<span className="text-[12px] text-meta dark:text-panel-dim">
											write-only
										</span>
									</span>
								</ConfigRow>
							)}
							{isOauth && (
								<>
									<ConfigRow label="Client ID">
										{server.oauthClientId ? (
											<span className="break-all font-mono text-[12px] text-foreground">
												{server.oauthClientId}
											</span>
										) : (
											<span className="text-[13.5px] text-meta dark:text-panel-dim">
												Dynamic Client Registration
											</span>
										)}
									</ConfigRow>
									<ConfigRow label="Client secret" last>
										{secretMask ? (
											<span className="inline-flex items-center gap-2.5">
												<span className="font-mono text-[12px] tracking-[0.08em] text-subtle dark:text-panel-dim">
													{secretMask}
												</span>
												<span className="text-[12px] text-meta dark:text-panel-dim">
													write-only
												</span>
											</span>
										) : (
											<span className="text-[13.5px] text-meta dark:text-panel-dim">
												Not set — using Dynamic Client Registration
											</span>
										)}
									</ConfigRow>
								</>
							)}
						</div>
					) : (
						<div className="mt-3.5 flex flex-col gap-[18px]">
							<div className="flex flex-col gap-[7px]">
								<label htmlFor="mcp-edit-name" className={LABEL_CLASS}>
									Name
								</label>
								<input
									id="mcp-edit-name"
									value={form.name}
									onChange={(e) => {
										handleFormChange("name", e.target.value);
									}}
									aria-invalid={!!fieldErrors.name}
									className={INPUT_CLASS}
								/>
								{fieldErrors.name && (
									<span className="text-[12.5px] text-destructive">
										{fieldErrors.name}
									</span>
								)}
							</div>
							<div className="flex flex-col gap-[7px]">
								<label htmlFor="mcp-edit-url" className={LABEL_CLASS}>
									Remote server address <span className="text-destructive">*</span>
								</label>
								<input
									id="mcp-edit-url"
									value={form.url}
									onChange={(e) => {
										handleFormChange("url", e.target.value);
									}}
									aria-invalid={!!fieldErrors.url}
									className={MONO_INPUT_CLASS}
								/>
								{fieldErrors.url && (
									<span className="text-[12.5px] text-destructive">
										{fieldErrors.url}
									</span>
								)}
							</div>
							<div className="flex flex-col gap-[7px]">
								<label htmlFor="mcp-edit-icon" className={LABEL_CLASS}>
									Icon URL
								</label>
								<input
									id="mcp-edit-icon"
									placeholder="https://…/icon.svg"
									value={form.iconUrl}
									onChange={(e) => {
										handleFormChange("iconUrl", e.target.value);
									}}
									className={MONO_INPUT_CLASS}
								/>
							</div>
							<div className="flex flex-col gap-[7px]">
								<label htmlFor="mcp-edit-description" className={LABEL_CLASS}>
									Description
								</label>
								<textarea
									id="mcp-edit-description"
									rows={3}
									value={form.description}
									onChange={(e) => {
										handleFormChange("description", e.target.value);
									}}
									className={`${INPUT_CLASS} resize-none leading-[1.55]`}
								/>
							</div>
							<div className="flex flex-col gap-1">
								<span className={LABEL_CLASS}>Authentication method</span>
								<span className="text-[13.5px] text-subtle dark:text-panel-body">
									{AUTH_TYPE_LABELS[server.authType]} — can&apos;t be changed
									after creation
								</span>
							</div>

							{server.authType === "api_key" && (
								<div className="flex flex-col gap-[7px]">
									<label htmlFor="mcp-edit-api-key" className={LABEL_CLASS}>
										API key
									</label>
									<input
										id="mcp-edit-api-key"
										type="password"
										placeholder="Leave blank to keep the current key"
										value={form.apiKey}
										onChange={(e) => {
											handleFormChange("apiKey", e.target.value);
										}}
										className={MONO_INPUT_CLASS}
									/>
								</div>
							)}

							{isOauth && (
								<>
									<div className="text-[12.5px] leading-[1.55] text-meta dark:text-panel-dim">
										{hasStoredSecret
											? "Client ID and secret are configured. Edit the Client ID as needed; leave the secret blank to keep it, or enter a new one to replace it."
											: "This server uses Dynamic Client Registration. Fill both fields to switch it to static credentials."}
									</div>
									<div className="flex flex-col gap-[7px]">
										<label htmlFor="mcp-edit-client-id" className={LABEL_CLASS}>
											Client ID
										</label>
										<input
											id="mcp-edit-client-id"
											placeholder="Enter your OAuth client ID"
											value={form.oauthClientId}
											onChange={(e) => {
												handleFormChange("oauthClientId", e.target.value);
											}}
											aria-invalid={!!fieldErrors.oauthClientId}
											className={MONO_INPUT_CLASS}
										/>
										{fieldErrors.oauthClientId && (
											<span className="text-[12.5px] text-destructive">
												{fieldErrors.oauthClientId}
											</span>
										)}
									</div>
									<div className="flex flex-col gap-[7px]">
										<label htmlFor="mcp-edit-client-secret" className={LABEL_CLASS}>
											Client secret
										</label>
										<div className="relative">
											<input
												id="mcp-edit-client-secret"
												type={showSecret ? "text" : "password"}
												placeholder={secretMask ?? "Enter your OAuth client secret"}
												value={form.oauthClientSecret}
												onChange={(e) => {
													handleFormChange("oauthClientSecret", e.target.value);
												}}
												aria-invalid={!!fieldErrors.oauthClientSecret}
												className={`${MONO_INPUT_CLASS} pr-10`}
											/>
											<button
												type="button"
												onClick={() => {
													setShowSecret((v) => !v);
												}}
												aria-label={showSecret ? "Hide secret" : "Show secret"}
												className="absolute right-3 top-1/2 -translate-y-1/2 cursor-pointer text-meta transition-colors hover:text-subtle dark:text-panel-dim dark:hover:text-foreground"
											>
												{showSecret ? (
													<EyeOff className="size-[15px]" />
												) : (
													<Eye className="size-[15px]" />
												)}
											</button>
										</div>
										{fieldErrors.oauthClientSecret && (
											<span className="text-[12.5px] text-destructive">
												{fieldErrors.oauthClientSecret}
											</span>
										)}
									</div>
								</>
							)}

							<div className="flex items-center gap-2.5 border-t border-hairline pt-3.5 dark:border-white/5">
								<button
									type="button"
									disabled={busy}
									onClick={() => {
										void handleDelete();
									}}
									className="cursor-pointer rounded-[7px] px-3.5 py-[7px] text-[12.5px] font-semibold text-[#B04A3A] transition-colors hover:bg-[#FBEFED] disabled:cursor-not-allowed disabled:opacity-50 dark:hover:bg-rose-950"
								>
									Delete server
								</button>
								{isOauth && (
									<button
										type="button"
										disabled={busy}
										title="Revokes all user connections — users will need to re-authenticate."
										onClick={() => {
											void handleReset();
										}}
										className="cursor-pointer rounded-[7px] px-3.5 py-[7px] text-[12.5px] font-semibold text-subtle transition-colors hover:bg-hover disabled:cursor-not-allowed disabled:opacity-50 dark:text-panel-body dark:hover:bg-white/10"
									>
										{isResetting ? "Resetting…" : "Reset connections"}
									</button>
								)}
							</div>
						</div>
					)}
				</div>

				{/* Right panel — connections */}
				<div className="flex min-w-0 flex-1 flex-col overflow-hidden bg-sidebar p-7 dark:bg-white/[0.02]">
					<ConnectedUsersPanel
						serverId={server.id}
						authType={server.authType}
						isAdmin={isAdmin}
						onResetAll={handleReset}
					/>
				</div>
			</div>

			<ForbiddenErrorDialog
				open={forbiddenOpen}
				onOpenChange={setForbiddenOpen}
				title="Insufficient privileges"
				message="You are not allowed to perform this action."
			/>
		</div>
	);
}
