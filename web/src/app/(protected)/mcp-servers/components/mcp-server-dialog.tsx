"use client";

import { useState, useEffect, useMemo, useRef } from "react";
import { api } from "@/lib/api/client";
import {
	ConnectionTestResult,
	MCPAuthType,
	MCPServer,
	MCPServerUpdate,
	OAuthSecretHint,
	OfficialMCPServer,
} from "@/types/mcp-servers";
import { useMcpServersStore } from "@/stores/mcp-servers-store";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import {
	X,
	CheckIcon,
	ChevronDown,
	Loader2,
	CircleCheck,
	CircleAlert,
	Eye,
	EyeOff,
} from "lucide-react";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import Image from "next/image";
import { SageInput, SageTextarea } from "@/components/ui/sage-input";
import { SageButton } from "@/components/ui/sage-button";
import { SageDropdownMenu } from "@/components/ui/sage-dropdown-menu";
import { SageAlert } from "@/components/ui/sage-alert";
import { SearchBar } from "@/components/ui/search-bar";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
	buildMCPServerCreatePayload,
	MCPServerCreateFormErrors,
	MCPServerCreateFormValues,
	requiresStaticOAuthCredentials,
	validateMCPServerCreateForm,
} from "../lib/mcp-server-create-form";

const DEFAULT_ICON =
	"https://pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev/assets/icons/mcp.png";
const CDN_HOST = "pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev";

const AUTH_TYPE_LABELS: Record<MCPAuthType, string> = {
	none: "None",
	api_key: "API Key",
	oauth2: "OAuth 2.0",
};

interface MCPServerDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	server?: MCPServer | null;
}

const emptyForm: MCPServerCreateFormValues = {
	name: "",
	url: "",
	description: "",
	authType: "none",
	apiKey: "",
	oauthClientId: "",
	oauthClientSecret: "",
	iconUrl: "",
};

export default function MCPServerDialog({
	open,
	onOpenChange,
	server,
}: MCPServerDialogProps) {
	const {
		createMcpServer,
		updateMcpServer,
		deleteMcpServer,
		resetMcpServerConnections,
	} = useMcpServersStore();
	const isEditMode = !!server;

	const [form, setForm] = useState<MCPServerCreateFormValues>(emptyForm);
	const [errors, setErrors] = useState<MCPServerCreateFormErrors>({});
	const [submitError, setSubmitError] = useState<string | null>(null);
	const [isSubmitting, setIsSubmitting] = useState(false);
	const [isResetting, setIsResetting] = useState(false);

	// OAuth static-credential edit state
	const [showSecret, setShowSecret] = useState(false);
	// Whether the saved server already has a static client secret (inferred from
	// the presence of a stored client_id — the two are always created together).
	// The secret itself is never returned by the API.
	const [hasStoredSecret, setHasStoredSecret] = useState(false);
	// Admin-only, non-reversible hint (last 4 + length) about the stored secret so
	// admins can confirm which one is set. Null when unavailable (e.g. non-admin).
	const [secretHint, setSecretHint] = useState<OAuthSecretHint | null>(null);

	// Test connection state
	const [testStatus, setTestStatus] = useState<
		"idle" | "testing" | "success" | "error"
	>("idle");
	const [testMessage, setTestMessage] = useState<string | null>(null);
	const testPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
	const testTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

	const clearTestPolling = () => {
		if (testPollRef.current) {
			clearInterval(testPollRef.current);
			testPollRef.current = null;
		}
		if (testTimeoutRef.current) {
			clearTimeout(testTimeoutRef.current);
			testTimeoutRef.current = null;
		}
	};

	const resetTestState = () => {
		clearTestPolling();
		setTestStatus("idle");
		setTestMessage(null);
	};

	// Stop polling if the dialog unmounts mid-authentication. Refs only, so the
	// empty dependency array is exhaustive.
	useEffect(() => {
		return () => {
			if (testPollRef.current) clearInterval(testPollRef.current);
			if (testTimeoutRef.current) clearTimeout(testTimeoutRef.current);
		};
	}, []);

	// ConnectorSearch state (create mode only)
	const [searchQuery, setSearchQuery] = useState("");
	const [officialServers, setOfficialServers] = useState<OfficialMCPServer[]>(
		[],
	);
	const [selectedOfficial, setSelectedOfficial] =
		useState<OfficialMCPServer | null>(null);
	const [errorDialogOpen, setErrorDialogOpen] = useState(false);

	// Fetch official servers
	useEffect(() => {
		if (open && !isEditMode) {
			api
				.get("/mcp-servers/official")
				.then((res) => { setOfficialServers(res.data); })
				.catch(() => {});
		}
	}, [open, isEditMode]);

	// Initialize form when dialog opens or server changes
	useEffect(() => {
		if (open && isEditMode && server) {
			setForm({
				name: server.name,
				url: server.url,
				description: server.description ?? "",
				authType: server.authType,
				apiKey: "",
				// client_id is a public identifier — prefill it so it's editable;
				// the secret is write-only and stays blank ("leave blank to keep").
				oauthClientId: server.oauthClientId ?? "",
				oauthClientSecret: "",
				iconUrl: server.iconUrl ?? "",
			});
		} else if (open && !isEditMode) {
			setForm(emptyForm);
			setSelectedOfficial(null);
			setSearchQuery("");
		}
		setErrors({});
		setSubmitError(null);
		setShowSecret(false);
		setHasStoredSecret(false);
		setSecretHint(null);
		// Reset test state inline (refs + stable setters) so the dependency array
		// stays exhaustive without depending on resetTestState.
		if (testPollRef.current) clearInterval(testPollRef.current);
		if (testTimeoutRef.current) clearTimeout(testTimeoutRef.current);
		testPollRef.current = null;
		testTimeoutRef.current = null;
		setTestStatus("idle");
		setTestMessage(null);
	}, [open, isEditMode, server]);

	// Editing an OAuth server: fetch the authoritative detail so the Client ID is
	// prefilled even when the cached list is stale. The secret is never returned;
	// a stored client_id implies a stored secret (created together).
	useEffect(() => {
		if (!(open && isEditMode && server && server.authType === "oauth2")) return;
		const controller = new AbortController();
		const { signal } = controller;
		void (async () => {
			try {
				const res = await api.get(`/mcp-servers/${server.id}`, { signal });
				const clientId = (res.data.oauthClientId as string | null) ?? "";
				setForm((prev) => ({ ...prev, oauthClientId: clientId }));
				setHasStoredSecret(!!clientId);
			} catch {
				// Aborted, or fall back to whatever the list prop provided.
			}
			// Secret hint is admin-only; a 403 for non-admins is expected.
			try {
				const res = await api.get<OAuthSecretHint>(
					`/mcp-servers/${server.id}/oauth-secret-hint`,
					{ signal },
				);
				setSecretHint(res.data);
				if (res.data.isSet) setHasStoredSecret(true);
			} catch {
				// Aborted, non-admin, or no hint — leave the masked placeholder.
			}
		})();
		return () => {
			controller.abort();
		};
	}, [open, isEditMode, server]);

	// Filter official servers: exclude installed, then apply search query
	const filteredServers = useMemo(() => {
		const available = officialServers.filter((s) => !s.isInstalled);
		if (!searchQuery.trim()) return available;
		const q = searchQuery.toLowerCase();
		return available.filter((s) => s.name.toLowerCase().includes(q));
	}, [officialServers, searchQuery]);

	// Whether the selected official server requires non-DCR credentials
	const isNonDcrOAuth = requiresStaticOAuthCredentials(selectedOfficial);

	const handleFormChange = (
		field: keyof MCPServerCreateFormValues,
		value: string,
	) => {
		setForm((prev) => ({ ...prev, [field]: value }));
		if (errors[field]) {
			setErrors((prev) => {
				const next = { ...prev };
				delete next[field];
				return next;
			});
		}
		// A prior test result no longer reflects the edited config.
		if (testStatus !== "idle") resetTestState();
	};

	const selectOfficialServer = (official: OfficialMCPServer) => {
		if (official.isInstalled) return;
		setSelectedOfficial(official);
		setSearchQuery("");
		setForm({
			name: official.name,
			url: official.url,
			description: official.description ?? "",
			authType: official.authType,
			apiKey: "",
			oauthClientId: "",
			oauthClientSecret: "",
			iconUrl: official.iconUrl ?? "",
		});
		setErrors({});
	};

	const clearSelection = () => {
		setSelectedOfficial(null);
		setForm(emptyForm);
		setSearchQuery("");
		setErrors({});
	};

	const handleCreate = async () => {
		const newErrors = validateMCPServerCreateForm(form, selectedOfficial);
		setErrors(newErrors);
		if (Object.keys(newErrors).length > 0) return;

		setSubmitError(null);
		setIsSubmitting(true);
		try {
			const payload = buildMCPServerCreatePayload(form);
			await createMcpServer(payload);
			onOpenChange(false);
		} catch (error) {
			setSubmitError(getApiErrorMessage(error, "Failed to create MCP server."));
		} finally {
			setIsSubmitting(false);
		}
	};

	const handleUpdate = async () => {
		if (!server) return;
		const newErrors: MCPServerCreateFormErrors = {};
		if (!form.name.trim()) newErrors.name = "Name is required.";
		if (!form.url.trim()) newErrors.url = "Server address is required.";
		setErrors(newErrors);
		if (Object.keys(newErrors).length > 0) return;

		setSubmitError(null);
		setIsSubmitting(true);
		try {
			const payload: MCPServerUpdate = {
				name: form.name,
				url: form.url,
				description: form.description || undefined,
				iconUrl: form.iconUrl || undefined,
				// Credentials are sent only when the field was filled in; a blank
				// field keeps the stored secret untouched.
				apiKey:
					server.authType === "api_key" && form.apiKey
						? form.apiKey
						: undefined,
				oauthClientId:
					server.authType === "oauth2" && form.oauthClientId
						? form.oauthClientId
						: undefined,
				oauthClientSecret:
					server.authType === "oauth2" && form.oauthClientSecret
						? form.oauthClientSecret
						: undefined,
			};
			await updateMcpServer(server.id, payload);
			onOpenChange(false);
		} catch (error) {
			setSubmitError(getApiErrorMessage(error, "Failed to update MCP server."));
		} finally {
			setIsSubmitting(false);
		}
	};

	const handleDelete = async () => {
		if (!server) return;
		if (!window.confirm("Are you sure you want to delete this MCP server?"))
			return;

		setSubmitError(null);
		setIsSubmitting(true);
		try {
			await deleteMcpServer(server.id);
			onOpenChange(false);
		} catch (error: unknown) {
			if (
				error instanceof Object &&
				"status" in error &&
				error.status === 403
			) {
				setErrorDialogOpen(true);
			} else {
				setSubmitError(
					getApiErrorMessage(error, "Failed to delete MCP server."),
				);
			}
		} finally {
			setIsSubmitting(false);
		}
	};

	const handleReset = async () => {
		if (!server) return;
		if (
			!window.confirm(
				"This will revoke all user connections to this MCP server. Users will need to re-authenticate. Continue?",
			)
		)
			return;

		setSubmitError(null);
		setIsResetting(true);
		try {
			await resetMcpServerConnections(server.id);
		} catch (error: unknown) {
			if (
				error instanceof Object &&
				"status" in error &&
				error.status === 403
			) {
				setErrorDialogOpen(true);
			} else {
				setSubmitError(
					getApiErrorMessage(error, "Failed to reset MCP server connections."),
				);
			}
		} finally {
			setIsResetting(false);
		}
	};

	const applyTestResult = (data: ConnectionTestResult) => {
		if (data.reachable) {
			const count = data.toolCount ?? 0;
			setTestStatus("success");
			setTestMessage(
				`Connection successful — ${count} tool${count === 1 ? "" : "s"} available.`,
			);
		} else {
			setTestStatus("error");
			setTestMessage(data.error ?? "Could not connect to the server.");
		}
	};

	const handleTest = async () => {
		clearTestPolling();
		if (!form.url.trim()) {
			setErrors((prev) => ({ ...prev, url: "Server address is required." }));
			return;
		}
		setTestStatus("testing");
		setTestMessage(null);

		// OAuth is per-user and interactive, so it's tested against the saved
		// server. An api_key edit with a blank field means "keep the stored key",
		// which likewise requires the saved config; everything else tests the
		// current form values without saving.
		const useSavedTest =
			isEditMode &&
			!!server &&
			(form.authType === "oauth2" ||
				(form.authType === "api_key" && !form.apiKey.trim()));

		try {
			if (useSavedTest && server) {
				const { data } = await api.post<ConnectionTestResult>(
					`/mcp-servers/${server.id}/test-connection`,
				);
				if (data.oauthRequired && data.authUrl) {
					const popup = window.open(
						data.authUrl,
						"_blank",
						"width=600,height=700",
					);
					setTestMessage("Waiting for authentication...");
					testPollRef.current = setInterval(() => {
						void (async () => {
							try {
								const res = await api.get(
									`/mcp-servers/${server.id}/is-connected`,
								);
								if (res.data.connected) {
									clearTestPolling();
									if (popup && !popup.closed) popup.close();
									const retry = await api.post<ConnectionTestResult>(
										`/mcp-servers/${server.id}/test-connection`,
									);
									applyTestResult(retry.data);
								}
							} catch {
								// keep polling until success or timeout
							}
						})();
					}, 2000);
					testTimeoutRef.current = setTimeout(() => {
						clearTestPolling();
						setTestStatus("error");
						setTestMessage("Authentication timed out. Please try again.");
					}, 60000);
					return;
				}
				applyTestResult(data);
			} else {
				const { data } = await api.post<ConnectionTestResult>(
					"/mcp-servers/test-connection",
					{
						url: form.url,
						authType: form.authType,
						apiKey:
							form.authType === "api_key"
								? form.apiKey || undefined
								: undefined,
					},
				);
				applyTestResult(data);
			}
		} catch (error) {
			setTestStatus("error");
			setTestMessage(getApiErrorMessage(error, "Failed to test connection."));
		}
	};

	const handleOpenChange = (newOpen: boolean) => {
		if (!newOpen) {
			setForm(emptyForm);
			setSelectedOfficial(null);
			setSearchQuery("");
			setErrors({});
			setSubmitError(null);
			resetTestState();
		}
		onOpenChange(newOpen);
	};

	const isOfficialIcon = (url?: string) =>
		url ? url.includes(CDN_HOST) : false;

	// Masked hint for the stored client secret: (length − 4) dots + last 4, so its
	// full length shows. Native placeholder behaviour hides it once you type and
	// restores it when the field is cleared.
	const secretPlaceholder = secretHint?.isSet
		? "•".repeat(Math.max(0, (secretHint.length ?? 4) - 4)) +
			(secretHint.last4 ?? "")
		: hasStoredSecret
			? "••••••••"
			: "Enter your OAuth client secret";

	const isTesting = testStatus === "testing";
	const testButton = (
		<SageButton
			color="outline"
			onClick={() => { void handleTest(); }}
			disabled={isTesting || isSubmitting || isResetting || !form.url.trim()}
		>
			{isTesting ? "Testing..." : "Test"}
		</SageButton>
	);

	return (
		<Dialog open={open} onOpenChange={handleOpenChange}>
			<ForbiddenErrorDialog
				open={errorDialogOpen}
				onOpenChange={setErrorDialogOpen}
				title="Insufficient privileges"
				message="You are not allowed to perform this action."
			/>
			<DialogContent
				className="sm:max-w-[560px] rounded-[28px] p-0 gap-0 overflow-hidden"
				showCloseButton={false}
			>
				{/* Header */}
				<div className="flex items-start justify-between px-8 pt-7 pb-0">
					<div>
						<DialogTitle className="font-[family-name:var(--font-jakarta-sans)] text-[22px] font-extrabold text-[#111111] dark:text-white tracking-[-0.02em]">
							{isEditMode ? "Edit MCP Server" : "Add MCP Server"}
						</DialogTitle>
						<p className="font-[family-name:var(--font-dm-sans)] text-[14px] text-[#8FA89E] dark:text-muted-foreground font-medium mt-2 leading-relaxed">
							{isEditMode
								? "Update your server configuration"
								: "Connect a new service to your workspace"}
						</p>
					</div>
					<button
						type="button"
						onClick={() => { handleOpenChange(false); }}
						className="shrink-0 flex items-center justify-center w-9 h-9 rounded-full bg-[#F5F8F6] dark:bg-white/10 text-[#6B7F76] hover:bg-[#EDF4F0] dark:hover:bg-white/15 transition-colors cursor-pointer"
					>
						<X className="w-4 h-4" />
					</button>
				</div>

				{/* Content */}
				<div className="px-8 pt-6 pb-2 max-h-[60vh] overflow-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
					{/* Create Mode: ConnectorSearch */}
					{!isEditMode && (
						<div className="mb-7">
							{selectedOfficial ? (
								<div className="flex items-center gap-3 rounded-[18px] border-[1.5px] border-[#E0E8E4] dark:border-white/10 px-4 py-3">
									<Image
										unoptimized
										src={selectedOfficial.iconUrl ?? DEFAULT_ICON}
										alt={selectedOfficial.name}
										width={24}
										height={24}
										className="shrink-0 rounded-md"
									/>
									<span className="font-[family-name:var(--font-dm-sans)] text-[14px] font-medium text-[#1E2D28] dark:text-foreground flex-1">
										{selectedOfficial.name}
									</span>
									<button
										type="button"
										onClick={clearSelection}
										className="text-[#8FA89E] hover:text-[#6B7F76] dark:text-muted-foreground dark:hover:text-foreground transition-colors cursor-pointer"
									>
										<X className="w-4 h-4" />
									</button>
								</div>
							) : (
								<SearchBar
									placeholder="Search official MCP servers..."
									value={searchQuery}
									onChange={setSearchQuery}
								/>
							)}

							{/* Dropdown list of official servers */}
							{!selectedOfficial && (
								<div className="mt-2 max-h-[200px] overflow-auto rounded-[18px] border-[1.5px] border-[#E0E8E4] dark:border-white/10 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
									{filteredServers.length === 0 ? (
										<div className="font-[family-name:var(--font-dm-sans)] p-4 text-[13px] text-[#A3B5AD] dark:text-muted-foreground text-center">
											No servers found
										</div>
									) : (
										filteredServers.map((s) => (
											<button
												key={s.name}
												type="button"
												disabled={s.isInstalled}
												onClick={() => { selectOfficialServer(s); }}
												className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-[#F8FAF9] dark:hover:bg-white/5 disabled:opacity-50 disabled:cursor-not-allowed transition-colors cursor-pointer first:rounded-t-[16px] last:rounded-b-[16px]"
											>
												<Image
													unoptimized
													src={s.iconUrl ?? DEFAULT_ICON}
													alt={s.name}
													width={24}
													height={24}
													className="shrink-0 rounded-md"
												/>
												<span className="font-[family-name:var(--font-dm-sans)] text-[14px] font-medium text-[#1E2D28] dark:text-foreground flex-1 truncate">
													{s.name}
												</span>
												{s.isInstalled && (
													<CheckIcon
														className="w-4 h-4 text-[#4CA882]"
														strokeWidth={3}
													/>
												)}
											</button>
										))
									)}
								</div>
							)}
						</div>
					)}

					{/* Edit Mode: Server preview card */}
					{isEditMode && server && (
						<div className="flex items-center gap-3.5 p-4 rounded-[18px] bg-[#F5F8F6] dark:bg-white/5 mb-7">
							<Image
								unoptimized
								src={server.iconUrl ?? DEFAULT_ICON}
								alt={server.name}
								width={44}
								height={44}
								className="shrink-0 rounded-full border-[1.5px] border-[#E0E8E4] dark:border-white/10 bg-white dark:bg-[#1C1C1C] p-1.5"
							/>
							<div className="min-w-0 flex-1">
								<div className="flex items-center gap-2">
									<span className="font-[family-name:var(--font-dm-sans)] text-[15px] font-bold text-[#1E2D28] dark:text-foreground truncate">
										{server.name}
									</span>
									{isOfficialIcon(server.iconUrl) && (
										<span className="font-[family-name:var(--font-dm-sans)] text-[11px] font-semibold text-[#6B7F76] dark:text-muted-foreground bg-[#E0E8E4] dark:bg-white/10 px-2 py-0.5 rounded-full">
											Official
										</span>
									)}
								</div>
								<p className="font-[family-name:var(--font-dm-sans)] text-[12.5px] text-[#8FA89E] dark:text-muted-foreground font-medium truncate mt-0.5">
									{server.url}
								</p>
							</div>
						</div>
					)}

					{/* Form fields */}
					<div className="space-y-[22px] mb-4">
						{/* Name */}
						<div>
							<label
								htmlFor="mcp-server-name"
								className="block font-[family-name:var(--font-dm-sans)] text-[13px] font-semibold text-[#1E2D28] dark:text-foreground mb-2"
							>
								Name
							</label>
							<SageInput
								id="mcp-server-name"
								placeholder="Server Name"
								value={form.name}
								onChange={(e) => { handleFormChange("name", e.target.value); }}
								error={!!errors.name}
								aria-required="true"
								aria-invalid={!!errors.name}
								aria-describedby={
									errors.name ? "mcp-server-name-error" : undefined
								}
							/>
							{errors.name && (
								<p
									id="mcp-server-name-error"
									className="font-[family-name:var(--font-dm-sans)] text-[13px] text-[#D45B45] mt-1.5"
								>
									{errors.name}
								</p>
							)}
						</div>

						{/* URL */}
						<div>
							<label
								htmlFor="mcp-server-url"
								className="block font-[family-name:var(--font-dm-sans)] text-[13px] font-semibold text-[#1E2D28] dark:text-foreground mb-2"
							>
								Remote Server Address
								<span className="text-[#D45B45] ml-0.5">*</span>
							</label>
							<SageInput
								id="mcp-server-url"
								placeholder="https://mcp.example.com/mcp"
								value={form.url}
								onChange={(e) => { handleFormChange("url", e.target.value); }}
								error={!!errors.url}
								aria-required="true"
								aria-invalid={!!errors.url}
								aria-describedby={
									errors.url ? "mcp-server-url-error" : undefined
								}
							/>
							{errors.url && (
								<p
									id="mcp-server-url-error"
									className="font-[family-name:var(--font-dm-sans)] text-[13px] text-[#D45B45] mt-1.5"
								>
									{errors.url}
								</p>
							)}
						</div>

						{/* Icon URL */}
						<div>
							<label
								htmlFor="mcp-server-icon-url"
								className="block font-[family-name:var(--font-dm-sans)] text-[13px] font-semibold text-[#1E2D28] dark:text-foreground mb-2"
							>
								Icon URL
							</label>
							<SageInput
								id="mcp-server-icon-url"
								placeholder="https://example.com/icon.png"
								value={form.iconUrl}
								onChange={(e) => { handleFormChange("iconUrl", e.target.value); }}
							/>
						</div>

						{/* Description */}
						<div>
							<label
								htmlFor="mcp-server-description"
								className="block font-[family-name:var(--font-dm-sans)] text-[13px] font-semibold text-[#1E2D28] dark:text-foreground mb-2"
							>
								Description
							</label>
							<SageTextarea
								id="mcp-server-description"
								placeholder="Description"
								value={form.description}
								onChange={(e) => { handleFormChange("description", e.target.value); }}
								rows={4}
							/>
						</div>

						{/* Auth Method */}
						{!isEditMode ? (
							<div>
								<label
									htmlFor="mcp-server-auth-type"
									className="block font-[family-name:var(--font-dm-sans)] text-[13px] font-semibold text-[#1E2D28] dark:text-foreground mb-2"
								>
									Authentication Method
								</label>
								<SageDropdownMenu
									trigger={
										<button
											id="mcp-server-auth-type"
											type="button"
											className="w-full rounded-full border-[1.5px] border-[#E0E8E4] dark:border-white/10 bg-[#FAFCFB] dark:bg-white/5 text-[14px] font-medium font-[family-name:var(--font-dm-sans)] text-[#1E2D28] dark:text-foreground h-auto py-3 px-[18px] flex items-center justify-between cursor-pointer hover:border-[#A3B5AD] focus:border-[#4CA882] transition-colors outline-none"
										>
											<span>{AUTH_TYPE_LABELS[form.authType]}</span>
											<ChevronDown className="size-4 text-[#8FA89E] shrink-0" />
										</button>
									}
									align="start"
									className="w-(--radix-dropdown-menu-trigger-width)"
									items={[
										{
											label: "None",
											onClick: () => { handleFormChange("authType", "none"); },
											active: form.authType === "none",
										},
										{
											label: "API Key",
											onClick: () => { handleFormChange("authType", "api_key"); },
											active: form.authType === "api_key",
										},
										{
											label: "OAuth 2.0",
											onClick: () => { handleFormChange("authType", "oauth2"); },
											active: form.authType === "oauth2",
										},
									]}
								/>
							</div>
						) : (
							<div>
								<p className="block font-[family-name:var(--font-dm-sans)] text-[13px] font-semibold text-[#1E2D28] dark:text-foreground mb-1">
									Authentication Method
								</p>
								<p className="font-[family-name:var(--font-dm-sans)] text-[14px] text-[#8FA89E] dark:text-muted-foreground font-medium">
									{server?.authType === "none"
										? "None"
										: server?.authType === "api_key"
											? "API Key"
											: "OAuth 2.0"}
								</p>
							</div>
						)}

						{/* API Key field */}
						{form.authType === "api_key" && (
							<div>
								<label
									htmlFor="mcp-server-api-key"
									className="block font-[family-name:var(--font-dm-sans)] text-[13px] font-semibold text-[#1E2D28] dark:text-foreground mb-2"
								>
									API Key
								</label>
								<SageInput
									id="mcp-server-api-key"
									type="password"
									placeholder={
										isEditMode
											? "Leave blank to keep current key"
											: "Enter your API Key"
									}
									value={form.apiKey}
									onChange={(e) => { handleFormChange("apiKey", e.target.value); }}
								/>
							</div>
						)}

						{/* OAuth fields */}
						{form.authType === "oauth2" && (
							<div className="space-y-[22px]">
								<p className="font-[family-name:var(--font-dm-sans)] text-[13px] text-[#8FA89E] dark:text-muted-foreground">
									{isEditMode
										? hasStoredSecret
											? "Client ID and secret are configured. Edit the Client ID as needed; leave the secret blank to keep it, or enter a new one to replace it."
											: "This server uses Dynamic Client Registration. Fill both fields to switch it to static credentials."
										: isNonDcrOAuth
											? "This server requires OAuth credentials."
											: "Leave empty to use Dynamic Client Registration (DCR). Only fill these if your MCP server requires static credentials."}
								</p>
								<div>
									<label
										htmlFor="mcp-server-oauth-client-id"
										className="block font-[family-name:var(--font-dm-sans)] text-[13px] font-semibold text-[#1E2D28] dark:text-foreground mb-2"
									>
										Client ID
										{isEditMode || isNonDcrOAuth ? "" : " (optional)"}
									</label>
									<SageInput
										id="mcp-server-oauth-client-id"
										placeholder="Enter your OAuth client ID"
										value={form.oauthClientId}
										onChange={(e) => { handleFormChange("oauthClientId", e.target.value); }}
										error={!!errors.oauthClientId}
										aria-required={isNonDcrOAuth}
										aria-invalid={!!errors.oauthClientId}
										aria-describedby={
											errors.oauthClientId
												? "mcp-server-oauth-client-id-error"
												: undefined
										}
									/>
									{errors.oauthClientId && (
										<p
											id="mcp-server-oauth-client-id-error"
											className="font-[family-name:var(--font-dm-sans)] text-[13px] text-[#D45B45] mt-1.5"
										>
											{errors.oauthClientId}
										</p>
									)}
								</div>
								<div>
									<label
										htmlFor="mcp-server-oauth-client-secret"
										className="block font-[family-name:var(--font-dm-sans)] text-[13px] font-semibold text-[#1E2D28] dark:text-foreground mb-2"
									>
										Client Secret
										{isEditMode || isNonDcrOAuth ? "" : " (optional)"}
									</label>
									<div className="relative">
										<SageInput
											id="mcp-server-oauth-client-secret"
											type={showSecret ? "text" : "password"}
											className="pr-11"
											placeholder={secretPlaceholder}
											value={form.oauthClientSecret}
											onChange={(e) => { handleFormChange("oauthClientSecret", e.target.value); }}
											error={!!errors.oauthClientSecret}
											aria-required={isNonDcrOAuth}
											aria-invalid={!!errors.oauthClientSecret}
											aria-describedby={
												errors.oauthClientSecret
													? "mcp-server-oauth-client-secret-error"
													: undefined
											}
										/>
										<button
											type="button"
											onClick={() => { setShowSecret((v) => !v); }}
											aria-label={showSecret ? "Hide secret" : "Show secret"}
											className="absolute right-4 top-1/2 -translate-y-1/2 text-[#8FA89E] hover:text-[#6B7F76] dark:text-muted-foreground dark:hover:text-foreground transition-colors cursor-pointer"
										>
											{showSecret ? (
												<EyeOff className="w-4 h-4" />
											) : (
												<Eye className="w-4 h-4" />
											)}
										</button>
									</div>
									{errors.oauthClientSecret && (
										<p
											id="mcp-server-oauth-client-secret-error"
											className="font-[family-name:var(--font-dm-sans)] text-[13px] text-[#D45B45] mt-1.5"
										>
											{errors.oauthClientSecret}
										</p>
									)}
								</div>
							</div>
						)}
					</div>
				</div>

				{/* Connection test result */}
				{testStatus !== "idle" && testMessage !== null && (
					<div className="px-8 pt-1 pb-2">
						<div
							className={`flex items-center gap-2.5 rounded-[14px] px-4 py-3 font-[family-name:var(--font-dm-sans)] text-[13px] font-medium ${
								testStatus === "success"
									? "bg-[#EAF6F0] dark:bg-[#4CA882]/10 text-[#2E7D5B] dark:text-[#7FD1AC]"
									: testStatus === "error"
										? "bg-[#FBECE8] dark:bg-[#D45B45]/10 text-[#C0492F] dark:text-[#E9927E]"
										: "bg-[#F5F8F6] dark:bg-white/5 text-[#6B7F76] dark:text-muted-foreground"
							}`}
						>
							{testStatus === "success" ? (
								<CircleCheck className="w-4 h-4 shrink-0" />
							) : testStatus === "error" ? (
								<CircleAlert className="w-4 h-4 shrink-0" />
							) : (
								<Loader2 className="w-4 h-4 shrink-0 animate-spin" />
							)}
							<span>{testMessage}</span>
						</div>
					</div>
				)}

				{/* Submission error */}
				{submitError && (
					<div className="px-8 pt-1 pb-2">
						<SageAlert
							key={submitError}
							variant="error"
							message={submitError}
						/>
					</div>
				)}

				{/* Footer */}
				<div className="flex items-center px-8 pt-5 pb-6 border-t border-[#F0F3F2] dark:border-white/5">
					{isEditMode ? (
						<>
							<SageButton
								color="destructive-ghost"
								onClick={() => { void handleDelete(); }}
								disabled={isSubmitting || isResetting}
							>
								Delete
							</SageButton>
							{server?.authType === "oauth2" && (
								<SageButton
									color="ghost"
									onClick={() => { void handleReset(); }}
									disabled={isSubmitting || isResetting}
								>
									{isResetting ? "Resetting..." : "Reset"}
								</SageButton>
							)}
							<div className="flex-1" />
							<div className="flex gap-2.5">
								{testButton}
								<SageButton
									color="outline"
									onClick={() => { handleOpenChange(false); }}
								>
									Cancel
								</SageButton>
								<SageButton onClick={() => { void handleUpdate(); }} disabled={isSubmitting}>
									{isSubmitting ? "Saving..." : "Save"}
								</SageButton>
							</div>
						</>
					) : (
						<>
							{testButton}
							<div className="flex-1" />
							<div className="flex gap-2.5">
								<SageButton
									color="outline"
									onClick={() => { handleOpenChange(false); }}
								>
									Cancel
								</SageButton>
								<SageButton onClick={() => { void handleCreate(); }} disabled={isSubmitting}>
									{isSubmitting ? "Creating..." : "Create server"}
								</SageButton>
							</div>
						</>
					)}
				</div>
			</DialogContent>
		</Dialog>
	);
}
