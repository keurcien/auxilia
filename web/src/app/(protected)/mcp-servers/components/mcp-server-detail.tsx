"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Eye, EyeOff, Plus, RotateCcw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import ResourceInUseDialog from "@/components/resource-in-use-dialog";
import { useConfirmDialog } from "@/components/providers/dialog-provider";
import { useDeleteMcpServer } from "@/hooks/use-delete-mcp-server";
import { Alert } from "@/components/ui/alert";
import { onPlainClick } from "@/components/ui/action-button";
import { DropdownMenu } from "@/components/ui/dropdown-menu";
import { GroupPicker } from "@/components/ui/group-picker";
import { VisibilityBadge } from "@/components/ui/visibility-badge";
import { VisibilityPicker } from "@/components/ui/visibility-picker";
import { ImageUpload } from "@/components/ui/image-upload";
import { UnderlineTabs } from "@/components/ui/underline-tabs";
import * as mcpServersApi from "@/lib/api/resources/mcp-servers";
import { getApiErrorMessage, toApiError } from "@/lib/api/errors";
import { groupOptions } from "@/lib/groups";
import { useIsMobile } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";
import { useMcpServersStore } from "@/stores/mcp-servers-store";
import { useUserStore } from "@/stores/user-store";
import {
	isPersonalAuth,
	MCPServer,
	MCPServerUpdate,
	OAuthSecretHint,
	OfficialMCPServer,
	ServiceCredentialProvider,
	usesUserCredentials,
} from "@/types/mcp-servers";
import { AuthTypeBadge } from "./auth-type-badge";
import type { ResourceVisibility } from "@/types/visibility";
import { ConnectedUsersPanel } from "./connected-users-panel";
import { ImagePreviewsPanel } from "./image-previews-panel";
import { ConnectionTestDialog } from "./connection-test-dialog";
import { MCPServerToolsPanel } from "./mcp-server-tools-panel";
import { MCPServerUsedBy } from "./mcp-server-used-by";
import { MCPServerUrlField } from "./mcp-server-url-field";
import { OAuthCallbackUrl } from "./oauth-callback-url";
import { OAuthConnectionFollowUpDialog } from "./oauth-connection-follow-up-dialog";
import { PersonalCredentialsDialog } from "./personal-credentials-dialog";
import { PersonalHeaderNamesField } from "./personal-header-names-field";
import { ServerIconTile } from "./server-icon-tile";
import { ServiceIdentityFields } from "./service-identity-fields";
import {
	HeaderButton,
	HeaderPrimaryButton,
	SubpageHeader,
} from "@/components/layout/subpage-header";
import { isOfficialIcon, slugify } from "../lib/constants";
import {
	buildServiceCredentialsPayload,
	parseServiceCredentialScopes,
	validatePersonalHeaderNames,
	validateServiceHeaders,
} from "../lib/mcp-server-create-form";
import { useConnectionTest } from "../lib/use-connection-test";
import {
	EMPTY_SERVICE_CREDENTIAL_FIELDS,
	hasProviderCredentialInput,
	knownServiceProvidersForUrl,
	providerLabel,
	ServiceCredentialFields,
	ServiceIdentityProvider,
	validateProviderCredentials,
} from "../lib/service-credential-providers";

const AUTH_TYPE_LABELS: Record<MCPServer["authType"], string> = {
	none: "None",
	api_key: "API Key Bearer",
	oauth2: "OAuth 2.0",
	service_identity: "Service identity",
	custom_http: "Custom HTTP",
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
	group: string;
	visibility: ResourceVisibility;
	teamIds: string[];
	apiKey: string;
	oauthClientId: string;
	oauthClientSecret: string;
	serviceCredentialProvider: ServiceCredentialProvider;
	serviceCredentialsJson: string;
	serviceCredentialScopes: string;
	serviceCredentialFields: ServiceCredentialFields;
	serviceHeaders: { name: string; value: string }[];
	personalHeaderNames: string[];
}

function formFromServer(server: MCPServer): EditFormValues {
	return {
		name: server.name,
		url: server.url,
		iconUrl: server.iconUrl ?? "",
		description: server.description ?? "",
		group: server.group ?? "",
		visibility: server.visibility ?? "workspace",
		teamIds: server.teamIds ?? [],
		apiKey: "",
		// client_id is a public identifier — prefill it so it's editable; the
		// secret is write-only and stays blank ("leave blank to keep").
		oauthClientId: server.oauthClientId ?? "",
		oauthClientSecret: "",
		serviceCredentialProvider:
			server.serviceCredentialProvider ?? "google_service_account",
		serviceCredentialsJson: "",
		serviceCredentialScopes:
			server.serviceCredentialScopes?.join(" ") ??
			"https://www.googleapis.com/auth/cloud-platform",
		serviceCredentialFields: { ...EMPTY_SERVICE_CREDENTIAL_FIELDS },
		serviceHeaders: [{ name: "", value: "" }],
		personalHeaderNames: server.personalHeaderNames ?? [],
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
	const confirmDialog = useConfirmDialog();
	const user = useUserStore((state) => state.user);
	const isAdmin = user?.role === "admin";
	const {
		mcpServers,
		updateMcpServer,
		applyMcpServer,
		duplicateMcpServer,
		resetMcpServerConnections,
	} = useMcpServersStore();

	const [server, setServer] = useState<MCPServer>(initialServer);
	const managedDatabaseHref =
		server.managedBy === "database" && server.managedResourceId
			? `/mcp-servers/database/${server.managedResourceId}`
			: null;
	const [isEditing, setIsEditing] = useState(initialEdit);
	const [disabledTools, setDisabledTools] = useState(
		initialServer.disabledTools ?? [],
	);
	const [rightPanel, setRightPanel] = useState<
		"tools" | "connections" | "images"
	>("tools");
	const [mobileTab, setMobileTab] = useState<"configuration" | "more">(
		"configuration",
	);
	const isMobile = useIsMobile();
	// ?edit=1 must not expose the editor to non-admins — the backend would
	// 403 the save, but the destructive controls shouldn't render at all.
	const editing = isEditing && isAdmin && managedDatabaseHref === null;
	const [form, setForm] = useState<EditFormValues>(
		formFromServer(initialServer),
	);
	const [fieldErrors, setFieldErrors] = useState<
		Partial<Record<keyof EditFormValues, string>>
	>({});
	const [submitError, setSubmitError] = useState<string | null>(null);
	const [isSubmitting, setIsSubmitting] = useState(false);
	const [isResetting, setIsResetting] = useState(false);
	const [forbiddenOpen, setForbiddenOpen] = useState(false);
	const [isOauthVerifying, setIsOauthVerifying] = useState(false);
	const [toolsRefreshRequest, setToolsRefreshRequest] = useState(0);
	const [showSecret, setShowSecret] = useState(false);
	const [credentialFileName, setCredentialFileName] = useState<string | null>(
		null,
	);
	const [catalogEntry, setCatalogEntry] = useState<OfficialMCPServer | null>(
		null,
	);
	const [imageFile, setImageFile] = useState<File | null>(null);
	const [removeImage, setRemoveImage] = useState(false);
	// Whether the saved server already has a static client secret; the secret
	// itself is never returned by the API.
	const [hasStoredSecret, setHasStoredSecret] = useState(
		!!initialServer.oauthClientId,
	);
	const [resetOauthCredentials, setResetOauthCredentials] = useState(false);
	// Admin-only, non-reversible hint (last 4 + length) about the stored secret.
	const [secretHint, setSecretHint] = useState<OAuthSecretHint | null>(null);
	// Don't let the async hint fetch clobber a Client ID the admin is editing.
	const clientIdDirtyRef = useRef(false);

	const {
		status: testStatus,
		message: testMessage,
		oauthFollowUpOpen,
		setOauthFollowUpOpen,
		reset: resetTest,
		runSavedTest,
		verifySavedConnection,
		runCandidateTest,
		credentialsServer: testCredentialsServer,
		closeCredentialsPrompt,
		completeCredentials,
	} = useConnectionTest();
	const userEntered = usesUserCredentials(server);

	useEffect(() => {
		const controller = new AbortController();
		void mcpServersApi
			.listOfficialMcpServers({ signal: controller.signal })
			.then((catalog) => {
				setCatalogEntry(
					catalog.find(
						(entry) =>
							entry.url === server.url ||
							entry.urlOptions?.some((option) => option.url === server.url) ||
							(Boolean(server.iconUrl) && entry.iconUrl === server.iconUrl),
					) ?? null,
				);
			})
			.catch(() => {
				if (!controller.signal.aborted) setCatalogEntry(null);
			});
		return () => {
			controller.abort();
		};
	}, [server.iconUrl, server.url]);

	// Admin-only secret hint for OAuth servers (403 for non-admins is expected).
	useEffect(() => {
		if (server.authType !== "oauth2") return;
		const controller = new AbortController();
		void (async () => {
			try {
				const hint = await mcpServersApi.getMcpServerOAuthSecretHint(
					server.id,
					{
						signal: controller.signal,
					},
				);
				setSecretHint(hint);
				if (hint.isSet) setHasStoredSecret(true);
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
		setCredentialFileName(null);
		setImageFile(null);
		setRemoveImage(false);
		setDisabledTools(server.disabledTools ?? []);
		setResetOauthCredentials(false);
		clientIdDirtyRef.current = false;
		resetTest();
		setMode(true);
	};

	const cancelEdit = () => {
		setFieldErrors({});
		setSubmitError(null);
		setImageFile(null);
		setRemoveImage(false);
		setResetOauthCredentials(false);
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

	const updateServiceHeader = (
		index: number,
		field: "name" | "value",
		value: string,
	) => {
		setForm((current) => ({
			...current,
			serviceHeaders: current.serviceHeaders.map((header, position) =>
				position === index ? { ...header, [field]: value } : header,
			),
		}));
		setFieldErrors(
			(current) =>
				Object.fromEntries(
					Object.entries(current).filter(([key]) => key !== "serviceHeaders"),
				) as typeof fieldErrors,
		);
		if (testStatus !== "idle") resetTest();
	};

	const handleTest = () => {
		// OAuth is per-user and interactive, so it's tested against the saved
		// server. An api_key edit with a blank field means "keep the stored
		// key", which likewise requires the saved config; everything else tests
		// the current form values without saving.
		const hasServiceCredentialReplacement =
			server.authType === "custom_http"
				? form.serviceHeaders.some((header) => header.name.trim())
				: hasProviderCredentialInput(
						form.serviceCredentialProvider as ServiceIdentityProvider,
						form.serviceCredentialFields,
						form.serviceCredentialsJson,
					);
		const serviceCredentialsJson = buildServiceCredentialsPayload(form);
		const useSavedTest =
			!editing ||
			isPersonalAuth(server) ||
			(server.authType === "api_key" && !form.apiKey.trim()) ||
			((server.authType === "service_identity" ||
				server.authType === "custom_http") &&
				!hasServiceCredentialReplacement);
		if (useSavedTest) {
			void runSavedTest(server);
		} else {
			void runCandidateTest({
				url: form.url,
				authType: server.authType,
				apiKey: form.apiKey,
				serviceCredentialProvider:
					server.authType === "custom_http"
						? "custom_http_headers"
						: form.serviceCredentialProvider,
				serviceCredentialsJson,
				serviceCredentialScopes: parseServiceCredentialScopes(
					form.serviceCredentialScopes,
				),
			});
		}
	};

	const handleOauthVerify = async () => {
		setIsOauthVerifying(true);
		const connected = await verifySavedConnection(server.id);
		if (connected) {
			setRightPanel("tools");
			setToolsRefreshRequest((request) => request + 1);
		}
		setIsOauthVerifying(false);
	};

	const handleSave = async () => {
		const errors: typeof fieldErrors = {};
		if (!form.name.trim()) errors.name = "Name is required.";
		if (!form.url.trim()) errors.url = "Server address is required.";
		if (form.visibility === "teams" && form.teamIds.length === 0) {
			errors.teamIds = "Select at least one team.";
		}
		// Setting static OAuth credentials on a server without them requires
		// both fields — one alone would be silently dropped by the backend.
		if (
			server.authType === "oauth2" &&
			!hasStoredSecret &&
			!resetOauthCredentials
		) {
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
		if (server.authType === "service_identity") {
			const providerChanged =
				form.serviceCredentialProvider !== server.serviceCredentialProvider;
			const hasReplacement = hasProviderCredentialInput(
				form.serviceCredentialProvider as ServiceIdentityProvider,
				form.serviceCredentialFields,
				form.serviceCredentialsJson,
			);
			if (
				providerChanged ||
				!server.serviceCredentialProvider ||
				hasReplacement
			) {
				const providerError = validateProviderCredentials(
					form.serviceCredentialProvider as ServiceIdentityProvider,
					form.serviceCredentialFields,
					form.serviceCredentialsJson,
				);
				if (providerError) errors.serviceCredentialsJson = providerError;
			}
		}
		if (server.authType === "custom_http" && userEntered) {
			const headerError = validatePersonalHeaderNames(
				form.personalHeaderNames,
			);
			if (headerError) errors.personalHeaderNames = headerError;
		} else if (server.authType === "custom_http") {
			const hasHeaders = form.serviceHeaders.some((header) =>
				header.name.trim(),
			);
			if (!server.serviceCredentialProvider || hasHeaders) {
				const headerError = validateServiceHeaders(form.serviceHeaders);
				if (headerError) errors.serviceHeaders = headerError;
			}
		}
		setFieldErrors(errors);
		if (Object.keys(errors).length > 0) return;

		setSubmitError(null);
		setIsSubmitting(true);
		try {
			const hasServiceCredentialReplacement =
				server.authType === "custom_http"
					? form.serviceHeaders.some((header) => header.name.trim())
					: hasProviderCredentialInput(
							form.serviceCredentialProvider as ServiceIdentityProvider,
							form.serviceCredentialFields,
							form.serviceCredentialsJson,
						);
			const usesSharedServiceCredential =
				!userEntered &&
				(server.authType === "service_identity" ||
					server.authType === "custom_http");
			const payload: MCPServerUpdate = {
				name: form.name,
				url: form.url,
				// Explicit null clears the stored value — undefined would be
				// dropped from the PATCH and silently keep the old one.
				description: form.description.trim() ? form.description : null,
				group: form.group || null,
				visibility: form.visibility,
				teamIds: form.teamIds,
				iconUrl: form.iconUrl.trim() ? form.iconUrl : null,
				// Credentials are sent only when the field was filled in; a blank
				// field keeps the stored secret untouched.
				apiKey:
					server.authType === "api_key" && !userEntered && form.apiKey
						? form.apiKey
						: undefined,
				personalHeaderNames:
					userEntered && server.authType === "custom_http"
						? form.personalHeaderNames.map((name) => name.trim())
						: undefined,
				oauthClientId:
					server.authType === "oauth2" && resetOauthCredentials
						? null
						: server.authType === "oauth2" && form.oauthClientId
							? form.oauthClientId
							: undefined,
				oauthClientSecret:
					server.authType === "oauth2" && resetOauthCredentials
						? null
						: server.authType === "oauth2" && form.oauthClientSecret
							? form.oauthClientSecret
							: undefined,
				serviceCredentialProvider: usesSharedServiceCredential
					? server.authType === "custom_http"
						? "custom_http_headers"
						: form.serviceCredentialProvider
					: undefined,
				serviceCredentialsJson:
					usesSharedServiceCredential && hasServiceCredentialReplacement
						? buildServiceCredentialsPayload(form)
						: undefined,
				serviceCredentialScopes: usesSharedServiceCredential
					? server.authType === "service_identity"
						? parseServiceCredentialScopes(form.serviceCredentialScopes)
						: []
					: undefined,
				disabledTools,
			};
			let updated = await updateMcpServer(server.id, payload);
			setServer(updated);
			if (imageFile) {
				const revision = await mcpServersApi.uploadMcpServerImage(
					server.id,
					imageFile,
				);
				updated = { ...updated, imageRevision: revision };
				applyMcpServer(updated);
				setServer(updated);
			} else if (removeImage && server.imageRevision) {
				await mcpServersApi.deleteMcpServerImage(server.id);
				updated = { ...updated, imageRevision: null };
				applyMcpServer(updated);
				setServer(updated);
			}
			if (server.authType === "oauth2") {
				if (resetOauthCredentials) {
					setHasStoredSecret(false);
					setSecretHint(null);
					setResetOauthCredentials(false);
				} else if (form.oauthClientSecret) {
					setHasStoredSecret(true);
					setSecretHint(null); // stale, the stored secret just changed
				}
			}
			setMode(false);
		} catch (error: unknown) {
			if (
				error instanceof Object &&
				"status" in error &&
				error.status === 403
			) {
				setForbiddenOpen(true);
			} else {
				setSubmitError(
					getApiErrorMessage(error, "Failed to update MCP server."),
				);
			}
		} finally {
			setIsSubmitting(false);
		}
	};

	const {
		guard: deleteGuard,
		clearGuard: clearDeleteGuard,
		requestDelete,
		confirmDetachAndDelete,
	} = useDeleteMcpServer({
		onDeleted: () => {
			router.push("/mcp-servers");
		},
		onError: (error) => {
			setSubmitError(getApiErrorMessage(error, "Failed to delete MCP server."));
			setIsSubmitting(false);
		},
		onForbidden: () => {
			setForbiddenOpen(true);
			setIsSubmitting(false);
		},
	});

	const handleDelete = async () => {
		setSubmitError(null);
		setIsSubmitting(true);
		await requestDelete(server);
		// Reset unless we navigated away — also covers the guard-dialog path,
		// where the delete continues from the dialog's own confirm.
		setIsSubmitting(false);
	};

	// Shared by the header ⋮ menu, the edit footer, and the connected-users
	// panel ("Reset all connections"). Returns true when the reset ran.
	const handleReset = async (): Promise<boolean> => {
		if (
			!(await confirmDialog({
				title: "Reset all connections?",
				description:
					"Every user connection to this MCP server will be revoked. Users will need to authenticate again.",
				confirmLabel: "Reset connections",
				destructive: true,
			}))
		)
			return false;
		setSubmitError(null);
		setIsResetting(true);
		try {
			await resetMcpServerConnections(server.id);
			return true;
		} catch (error: unknown) {
			if (
				error instanceof Object &&
				"status" in error &&
				error.status === 403
			) {
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

	const handleDuplicate = async () => {
		setSubmitError(null);
		try {
			const created = await duplicateMcpServer(server.id);
			toast.success(`Duplicated as “${created.name}”.`);
			router.push(`/mcp-servers/${created.id}?edit=1`);
		} catch (error: unknown) {
			if (toApiError(error).status === 403) {
				setForbiddenOpen(true);
			} else {
				setSubmitError(
					getApiErrorMessage(error, "Could not duplicate the MCP server."),
				);
			}
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

	const credentialsServer = userEntered ? server : undefined;
	const secondaryPanel = editing ? (
		<MCPServerToolsPanel
			key={`${server.id}-${toolsRefreshRequest}`}
			serverId={server.id}
			credentialsServer={credentialsServer}
			disabledTools={disabledTools}
			onDisabledToolsChange={setDisabledTools}
			disabled={busy}
		/>
	) : (
		<div className="flex min-h-0 flex-1 flex-col">
			<div className="mb-5 flex w-fit shrink-0 rounded-[8px] bg-hover p-1 dark:bg-white/5">
				{(isAdmin
					? (["tools", "connections", "images"] as const)
					: (["tools", "connections"] as const)
				).map((panel) => (
					<button
						key={panel}
						type="button"
						onClick={() => {
							setRightPanel(panel);
						}}
						className={`cursor-pointer rounded-[6px] px-3 py-1.5 text-[11.5px] font-semibold capitalize transition-colors ${
							rightPanel === panel
								? "bg-card text-foreground shadow-sm"
								: "text-meta hover:text-foreground dark:text-panel-dim"
						}`}
					>
						{panel}
					</button>
				))}
			</div>
			{rightPanel === "tools" ? (
				<MCPServerToolsPanel
					key={`${server.id}-${toolsRefreshRequest}`}
					serverId={server.id}
					credentialsServer={credentialsServer}
					disabledTools={server.disabledTools ?? []}
					readOnly
				/>
			) : rightPanel === "images" && isAdmin ? (
				<ImagePreviewsPanel key={server.id} serverId={server.id} />
			) : (
				<ConnectedUsersPanel
					serverId={server.id}
					serverName={server.name}
					authType={server.authType}
					credentialScope={server.credentialScope}
					personalHeaderNames={server.personalHeaderNames}
					isAdmin={isAdmin}
					onResetAll={handleReset}
					onReconnect={() => {
						void runSavedTest(server);
					}}
					connectionRevision={testStatus}
				/>
			)}
		</div>
	);

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
							disabled={
								busy ||
								(form.visibility === "teams" && form.teamIds.length === 0)
							}
							onClick={() => {
								void handleSave();
							}}
						>
							{isSubmitting ? "Saving…" : "Save changes"}
						</HeaderPrimaryButton>
					</>
				) : (
					isAdmin && (
						managedDatabaseHref ? (
							<HeaderButton href={managedDatabaseHref}>
								Manage database
							</HeaderButton>
						) : (
							<>
								<HeaderButton
									href={`/mcp-servers/${server.id}?edit=1`}
									onClick={onPlainClick(startEdit)}
								>
									Edit server
								</HeaderButton>
								<DropdownMenu
									items={[
										{
											label: "Duplicate",
											onClick: () => {
												void handleDuplicate();
											},
										},
										...(isPersonalAuth(server)
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
					)
				)}
			</SubpageHeader>

			<div className="flex min-h-0 flex-1 flex-col md:flex-row">
				{/* Left panel — identity + configuration */}
				<div className="min-w-0 overflow-y-auto border-b border-border bg-background p-7 pb-11 md:flex-[1.05] md:border-b-0 md:border-r [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
					<div className="flex items-center gap-4">
						<ServerIconTile
							iconUrl={editing ? form.iconUrl || null : server.iconUrl}
							serverId={server.id}
							imageRevision={server.imageRevision}
							name={server.name}
							size={52}
						/>
						<div className="min-w-0 flex-1">
							<div className="flex flex-wrap items-center gap-2.5">
								<h1 className="font-display text-[26px] font-bold tracking-[-0.03em] text-foreground">
									{server.name}
								</h1>
								<AuthTypeBadge
									authType={server.authType}
									credentialScope={server.credentialScope}
								/>
								{isOfficialIcon(server.iconUrl) && (
									<span className="rounded-[4px] bg-hover px-[9px] py-[3px] text-[11px] font-semibold text-subtle dark:bg-white/10 dark:text-panel-body">
										Official
									</span>
								)}
							</div>
							<div className="mt-1 truncate font-mono text-[11.5px] text-meta dark:text-panel-dim">
								{managedDatabaseHref
									? (server.managedEndpoint ?? "Managed database")
									: server.url}
							</div>
						</div>
					</div>

					<UnderlineTabs
						tabs={[
							{ key: "configuration", label: "Configuration" },
							{ key: "more", label: "More" },
						]}
						value={mobileTab}
						onChange={setMobileTab}
						className="mt-6 border-b border-border md:hidden"
					/>

					<div
						className={cn(
							mobileTab === "more" && "hidden md:block",
						)}
					>
					{submitError && (
						<div className="mt-5">
							<Alert
								key={submitError}
								variant="error"
								message={submitError}
							/>
						</div>
					)}

					<div className="mb-1.5 mt-[30px]">
						<span className="text-[10.5px] font-semibold text-subtle dark:text-panel-dim">
							Configuration
						</span>
					</div>

					{!editing ? (
						<div>
							<ConfigRow label="Name">
								<span className="text-[13.5px] text-foreground">
									{server.name}
								</span>
							</ConfigRow>
							<ConfigRow
								label={
									managedDatabaseHref
										? "Database endpoint"
										: "Remote server address"
								}
							>
								<span className="break-all font-mono text-[12px] text-foreground">
									{managedDatabaseHref
										? (server.managedEndpoint ?? "Managed database")
										: server.url}
								</span>
							</ConfigRow>
							<ConfigRow label="Description">
								{server.description ? (
									<span className="text-[13.5px] leading-[1.55] text-foreground">
										{server.description}
									</span>
								) : (
									<span className="text-[13.5px] text-meta dark:text-panel-dim">
										Not available
									</span>
								)}
							</ConfigRow>
							<ConfigRow label="Visibility">
								<VisibilityBadge
									visibility={server.visibility ?? "workspace"}
									teamIds={server.teamIds}
									showTeams
								/>
							</ConfigRow>
							<ConfigRow
								label="Authentication method"
								last={
									server.authType === "none" ||
									(userEntered && server.authType === "api_key")
								}
							>
								<span className="text-[13.5px] text-foreground">
									{AUTH_TYPE_LABELS[server.authType]}
									<span className="text-meta dark:text-panel-dim">
										{isPersonalAuth(server)
											? " (personal: each user connects)"
											: server.authType === "none"
												? ""
												: " (shared by everyone)"}
									</span>
								</span>
							</ConfigRow>
							{userEntered && server.authType === "custom_http" && (
								<ConfigRow label="Personal headers" last>
									<span className="break-all font-mono text-[12px] text-foreground">
										{(server.personalHeaderNames ?? []).join(", ") ||
											"Not configured"}
									</span>
								</ConfigRow>
							)}
							{server.authType === "api_key" && !userEntered && (
								<ConfigRow label="API Key Bearer" last>
									<span className="inline-flex items-center gap-2.5">
										<span className="font-mono text-[12px] text-subtle dark:text-panel-dim">
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
									<ConfigRow label="Callback URL">
										<OAuthCallbackUrl showLabel={false} />
									</ConfigRow>
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
												<span className="font-mono text-[12px] text-subtle dark:text-panel-dim">
													{secretMask}
												</span>
												<span className="text-[12px] text-meta dark:text-panel-dim">
													write-only
												</span>
											</span>
										) : (
											<span className="text-[13.5px] text-meta dark:text-panel-dim">
												Not set, using Dynamic Client Registration
											</span>
										)}
									</ConfigRow>
								</>
							)}
							{(server.authType === "service_identity" ||
								server.authType === "custom_http") &&
								!userEntered && (
								<>
									<ConfigRow label="Credential provider">
										<span className="text-[13.5px] text-foreground">
											{server.serviceCredentialProvider
												? providerLabel(server.serviceCredentialProvider)
												: "Not configured"}
										</span>
									</ConfigRow>
									<ConfigRow
										label={
											server.serviceCredentialProvider === "custom_http_headers"
												? "Configuration"
												: "Principal"
										}
									>
										<span className="break-all font-mono text-[12px] text-foreground">
											{server.serviceCredentialPrincipal ?? "Not available"}
										</span>
									</ConfigRow>
									{(server.serviceCredentialProvider ===
										"google_service_account" ||
										server.serviceCredentialProvider ===
											"oauth_client_credentials") && (
										<ConfigRow label="OAuth scopes">
											<span className="break-all font-mono text-[12px] text-foreground">
												{server.serviceCredentialScopes?.join(", ") ||
													"Provider default"}
											</span>
										</ConfigRow>
									)}
									<ConfigRow
										label={
											server.serviceCredentialProvider === "custom_http_headers"
												? "Header values"
												: "Credential values"
										}
										last
									>
										<span className="inline-flex items-center gap-2.5">
											<span className="font-mono text-[12px] text-subtle dark:text-panel-dim">
												••••••••
											</span>
											<span className="text-[12px] text-meta dark:text-panel-dim">
												write-only
											</span>
										</span>
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
									Remote server address{" "}
									<span className="text-destructive">*</span>
								</label>
								<MCPServerUrlField
									id="mcp-edit-url"
									value={form.url}
									options={catalogEntry?.urlOptions ?? []}
									onChange={(value) => {
										handleFormChange("url", value);
									}}
									placeholder="https://mcp.example.com/mcp"
									invalid={Boolean(fieldErrors.url)}
									inputClassName={MONO_INPUT_CLASS}
								/>
								{fieldErrors.url && (
									<span className="text-[12.5px] text-destructive">
										{fieldErrors.url}
									</span>
								)}
							</div>
							<div className="flex flex-col gap-[7px]">
								<label htmlFor="mcp-edit-icon-url" className={LABEL_CLASS}>
									Icon URL
								</label>
								<input
									id="mcp-edit-icon-url"
									value={form.iconUrl}
									onChange={(e) => {
										handleFormChange("iconUrl", e.target.value);
									}}
									placeholder="https://example.com/icon.png"
									className={MONO_INPUT_CLASS}
								/>
							</div>
							<ImageUpload
								currentUrl={
									server.imageRevision
										? mcpServersApi.mcpServerImageUrl(
												server.id,
												server.imageRevision,
											)
										: form.iconUrl || null
								}
								file={imageFile}
								removed={removeImage}
								onFileChange={(file) => {
									setImageFile(file);
									if (file) setRemoveImage(false);
								}}
								onRemove={() => {
									if (imageFile) {
										setImageFile(null);
										return;
									}
									setImageFile(null);
									if (server.imageRevision) {
										setRemoveImage(true);
									} else {
										handleFormChange("iconUrl", "");
									}
								}}
								label="Uploaded logo"
								className="rounded-[12px] border border-hairline bg-sidebar p-3 dark:border-white/5"
							/>
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
							<GroupPicker
								value={form.group}
								groups={groupOptions(mcpServers)}
								onChange={(group) => {
									handleFormChange("group", group);
								}}
							/>
							<VisibilityPicker
								visibility={form.visibility}
								teamIds={form.teamIds}
								onChange={(visibility, teamIds) => {
									setForm((current) => ({
										...current,
										visibility,
										teamIds,
									}));
								}}
							/>
							<div className="flex flex-col gap-1">
								<span className={LABEL_CLASS}>Authentication method</span>
								<span className="text-[13.5px] text-subtle dark:text-panel-body">
									{userEntered ? "Personal " : ""}
									{AUTH_TYPE_LABELS[server.authType]}, can&apos;t be changed
									after creation
								</span>
							</div>

							{userEntered && server.authType === "api_key" && (
								<div className="text-[12.5px] leading-[1.55] text-meta dark:text-panel-dim">
									Each user enters their own API key when they connect. There
									is no shared key to manage here.
								</div>
							)}

							{userEntered && server.authType === "custom_http" && (
								<div className="flex flex-col gap-3 rounded-xl border border-border bg-sidebar p-[18px] dark:bg-white/5">
									<PersonalHeaderNamesField
										names={form.personalHeaderNames}
										onChange={(names) => {
											setForm((current) => ({
												...current,
												personalHeaderNames: names,
											}));
											setFieldErrors((current) => ({
												...current,
												personalHeaderNames: undefined,
											}));
										}}
										error={fieldErrors.personalHeaderNames}
										inputClassName={MONO_INPUT_CLASS}
									/>
									<span className="text-[12px] text-meta dark:text-panel-dim">
										Each user fills in their own values. Changing the header
										names deletes every user&apos;s saved values.
									</span>
								</div>
							)}

							{server.authType === "api_key" && !userEntered && (
								<div className="flex flex-col gap-[7px]">
									<label htmlFor="mcp-edit-api-key" className={LABEL_CLASS}>
										API Key Bearer
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
										{resetOauthCredentials
											? "Static OAuth credentials are marked for removal."
											: hasStoredSecret
											? "Client ID and secret are configured. Edit the Client ID as needed; leave the secret blank to keep it, or enter a new one to replace it."
											: "This server uses Dynamic Client Registration. Fill both fields to switch it to static credentials."}
									</div>
									<OAuthCallbackUrl />
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
											disabled={resetOauthCredentials}
											aria-invalid={!!fieldErrors.oauthClientId}
											className={`${MONO_INPUT_CLASS} disabled:cursor-not-allowed disabled:opacity-50`}
										/>
										{fieldErrors.oauthClientId && (
											<span className="text-[12.5px] text-destructive">
												{fieldErrors.oauthClientId}
											</span>
										)}
									</div>
									<div className="flex flex-col gap-[7px]">
										<label
											htmlFor="mcp-edit-client-secret"
											className={LABEL_CLASS}
										>
											Client secret
										</label>
										<div className="relative">
											<input
												id="mcp-edit-client-secret"
												type={showSecret ? "text" : "password"}
												placeholder={
													secretMask ?? "Enter your OAuth client secret"
												}
												value={form.oauthClientSecret}
												onChange={(e) => {
													handleFormChange("oauthClientSecret", e.target.value);
												}}
												disabled={resetOauthCredentials}
												aria-invalid={!!fieldErrors.oauthClientSecret}
												className={`${MONO_INPUT_CLASS} pr-10 disabled:cursor-not-allowed disabled:opacity-50`}
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
									{hasStoredSecret &&
										(resetOauthCredentials ? (
											<div className="flex flex-col gap-3 rounded-lg border border-destructive/25 bg-destructive/5 px-3.5 py-3 sm:flex-row sm:items-center sm:justify-between">
												<p className="text-[12.5px] leading-[1.5] text-destructive">
													Saving will remove the stored Client ID and secret,
													clear existing OAuth connections, and enable Dynamic
													Client Registration.
												</p>
												<button
													type="button"
													onClick={() => {
														setResetOauthCredentials(false);
														setForm((current) => ({
															...current,
															oauthClientId: server.oauthClientId ?? "",
															oauthClientSecret: "",
														}));
													}}
													className="shrink-0 cursor-pointer rounded-md border border-destructive/30 px-3 py-1.5 text-[12px] font-semibold text-destructive transition-colors hover:bg-destructive/10"
												>
													Undo reset
												</button>
											</div>
										) : (
											<button
												type="button"
												disabled={busy}
												onClick={() => {
													setResetOauthCredentials(true);
													setForm((current) => ({
														...current,
														oauthClientId: "",
														oauthClientSecret: "",
													}));
													setFieldErrors((current) => ({
														...current,
														oauthClientId: undefined,
														oauthClientSecret: undefined,
													}));
													if (testStatus !== "idle") resetTest();
												}}
												className="inline-flex w-fit cursor-pointer items-center gap-2 rounded-md border border-destructive/30 px-3 py-2 text-[12.5px] font-semibold text-destructive transition-colors hover:bg-destructive/10 disabled:cursor-not-allowed disabled:opacity-50"
											>
												<RotateCcw className="size-3.5" />
												Reset to Dynamic Client Registration
											</button>
										))}
								</>
							)}

							{(server.authType === "service_identity" ||
								server.authType === "custom_http") &&
								!userEntered && (
								<div className="flex flex-col gap-[18px] rounded-xl border border-border bg-sidebar p-[18px] dark:bg-white/5">
									<div className="text-[12.5px] leading-[1.55] text-meta dark:text-panel-dim">
										The stored credential is write-only. Providing a replacement
										updates it for every user and agent that can access this
										server.
									</div>
									{server.authType === "service_identity" && (
										<ServiceIdentityFields
											provider={
												form.serviceCredentialProvider as ServiceIdentityProvider
											}
											allowedProviders={
												catalogEntry?.serviceCredentialProviders ??
												knownServiceProvidersForUrl(server.url)
											}
											fields={form.serviceCredentialFields}
											scopes={form.serviceCredentialScopes}
											credentialFileName={credentialFileName}
											error={fieldErrors.serviceCredentialsJson}
											replacement
											onProviderChange={(provider) => {
												setCredentialFileName(null);
												setForm((current) => ({
													...current,
													serviceCredentialProvider: provider,
													serviceCredentialsJson: "",
													serviceCredentialFields: {
														...EMPTY_SERVICE_CREDENTIAL_FIELDS,
													},
													serviceCredentialScopes:
														provider === "google_service_account"
															? "https://www.googleapis.com/auth/cloud-platform"
															: "",
												}));
												setFieldErrors((current) => ({
													...current,
													serviceCredentialsJson: undefined,
												}));
												if (testStatus !== "idle") resetTest();
											}}
											onFieldsChange={(fields) => {
												setForm((current) => ({
													...current,
													serviceCredentialFields: fields,
												}));
												setFieldErrors((current) => ({
													...current,
													serviceCredentialsJson: undefined,
												}));
												if (testStatus !== "idle") resetTest();
											}}
											onScopesChange={(scopes) => {
												handleFormChange("serviceCredentialScopes", scopes);
											}}
											onGoogleCredentialsChange={(contents, fileName) => {
												handleFormChange("serviceCredentialsJson", contents);
												setCredentialFileName(fileName);
											}}
											onError={(message) => {
												setFieldErrors((current) => ({
													...current,
													serviceCredentialsJson: message,
												}));
											}}
										/>
									)}
									{server.authType === "custom_http" && (
										<div className="flex flex-col gap-3">
											<div className="flex items-center justify-between gap-3">
												<span className={LABEL_CLASS}>
													Replacement HTTP headers
												</span>
												<button
													type="button"
													onClick={() => {
														setForm((current) => ({
															...current,
															serviceHeaders: [
																...current.serviceHeaders,
																{ name: "", value: "" },
															],
														}));
													}}
													className="inline-flex cursor-pointer items-center gap-1.5 text-[12px] font-semibold text-petrol hover:underline dark:text-panel-terminal"
												>
													<Plus className="size-3.5" />
													Add header
												</button>
											</div>
											{form.serviceHeaders.map((header, index) => (
												<div
													key={index}
													className="grid grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)_32px] gap-2"
												>
													<input
														aria-label={`Header ${index + 1} name`}
														placeholder="Authorization"
														value={header.name}
														onChange={(e) => {
															updateServiceHeader(
																index,
																"name",
																e.target.value,
															);
														}}
														className={MONO_INPUT_CLASS}
													/>
													<input
														aria-label={`Header ${index + 1} value`}
														type="password"
														placeholder="Bearer ••••••••"
														value={header.value}
														onChange={(e) => {
															updateServiceHeader(
																index,
																"value",
																e.target.value,
															);
														}}
														className={MONO_INPUT_CLASS}
													/>
													<button
														type="button"
														aria-label={`Remove header ${index + 1}`}
														onClick={() => {
															setForm((current) => ({
																...current,
																serviceHeaders: current.serviceHeaders.filter(
																	(_, position) => position !== index,
																),
															}));
														}}
														className="flex cursor-pointer items-center justify-center rounded-lg text-meta transition-colors hover:bg-destructive/10 hover:text-destructive"
													>
														<Trash2 className="size-4" />
													</button>
												</div>
											))}
											{fieldErrors.serviceHeaders && (
												<span className="text-[12.5px] text-destructive">
													{fieldErrors.serviceHeaders}
												</span>
											)}
											<span className="text-[12px] text-meta dark:text-panel-dim">
												Leave all rows empty to keep the stored headers.
												Entering any header replaces the complete set.
											</span>
										</div>
									)}
								</div>
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
								{isPersonalAuth(server) && (
									<button
										type="button"
										disabled={busy}
										title="Revokes all user connections, users will need to re-authenticate."
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
					{!editing && <MCPServerUsedBy serverId={server.id} />}
					</div>
					{isMobile && mobileTab === "more" && (
						<div className="flex min-w-0 flex-col pt-5">
							{secondaryPanel}
						</div>
					)}
				</div>

				{/* Right panel — tools while editing, connections otherwise */}
				{!isMobile && (
					<div className="hidden min-w-0 flex-1 flex-col overflow-hidden bg-sidebar p-7 md:flex dark:bg-white/[0.02]">
						{secondaryPanel}
					</div>
				)}
			</div>

			<ForbiddenErrorDialog
				open={forbiddenOpen}
				onOpenChange={setForbiddenOpen}
				title="Insufficient privileges"
				message="You are not allowed to perform this action."
			/>
			<ResourceInUseDialog
				open={deleteGuard !== null}
				onOpenChange={(open) => {
					if (!open) clearDeleteGuard();
				}}
				resourceLabel="MCP server"
				resourceName={deleteGuard?.server.name ?? null}
				agents={deleteGuard?.agents ?? []}
				consequence="they lose its tools"
				onConfirm={confirmDetachAndDelete}
			/>
			<OAuthConnectionFollowUpDialog
				open={oauthFollowUpOpen}
				onOpenChange={setOauthFollowUpOpen}
				onVerify={() => {
					void handleOauthVerify();
				}}
				isVerifying={isOauthVerifying}
				message={
					testMessage === "Waiting for authentication…" ? null : testMessage
				}
			/>
			<ConnectionTestDialog
				status={testStatus}
				message={testMessage}
				onClose={resetTest}
			/>
			<PersonalCredentialsDialog
				server={testCredentialsServer}
				onOpenChange={(open) => {
					if (!open) closeCredentialsPrompt();
				}}
				onSaved={completeCredentials}
			/>
		</div>
	);
}
