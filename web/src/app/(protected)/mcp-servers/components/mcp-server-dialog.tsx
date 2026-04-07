"use client";

import { useState, useEffect, useMemo } from "react";
import { api } from "@/lib/api/client";
import {
	MCPAuthType,
	MCPServer,
	MCPServerCreate,
	MCPServerUpdate,
	OfficialMCPServer,
} from "@/types/mcp-servers";
import { useMcpServersStore } from "@/stores/mcp-servers-store";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { X, CheckIcon, ChevronDown } from "lucide-react";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import Image from "next/image";
import { SageInput, SageTextarea } from "@/components/ui/sage-input";
import { SageButton } from "@/components/ui/sage-button";
import { SageDropdownMenu } from "@/components/ui/sage-dropdown-menu";
import { SearchBar } from "@/components/ui/search-bar";

const DEFAULT_ICON = "https://storage.googleapis.com/choose-assets/mcp.png";
const GCS_HOST = "storage.googleapis.com";

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

interface FormState {
	name: string;
	url: string;
	description: string;
	authType: MCPAuthType;
	apiKey: string;
	oauthClientId: string;
	oauthClientSecret: string;
	iconUrl: string;
}

const emptyForm: FormState = {
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
	const { addMcpServer, updateMcpServer, removeMcpServer } =
		useMcpServersStore();
	const isEditMode = !!server;

	const [form, setForm] = useState<FormState>(emptyForm);
	const [errors, setErrors] = useState<Record<string, string>>({});
	const [isSubmitting, setIsSubmitting] = useState(false);
	const [isResetting, setIsResetting] = useState(false);

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
				.then((res) => setOfficialServers(res.data))
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
				oauthClientId: "",
				oauthClientSecret: "",
				iconUrl: server.iconUrl ?? "",
			});
		} else if (open && !isEditMode) {
			setForm(emptyForm);
			setSelectedOfficial(null);
			setSearchQuery("");
		}
		setErrors({});
	}, [open, isEditMode, server]);

	// Filter official servers: exclude installed, then apply search query
	const filteredServers = useMemo(() => {
		const available = officialServers.filter((s) => !s.isInstalled);
		if (!searchQuery.trim()) return available;
		const q = searchQuery.toLowerCase();
		return available.filter((s) => s.name.toLowerCase().includes(q));
	}, [officialServers, searchQuery]);

	// Whether the selected official server requires non-DCR credentials
	const isNonDcrOAuth =
		selectedOfficial?.supportsDcr === false &&
		selectedOfficial?.authType === "oauth2";

	const handleFormChange = (field: keyof FormState, value: string) => {
		setForm((prev) => ({ ...prev, [field]: value }));
		if (errors[field]) {
			setErrors((prev) => {
				const next = { ...prev };
				delete next[field];
				return next;
			});
		}
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

	const validate = (): boolean => {
		const newErrors: Record<string, string> = {};

		if (!form.name.trim()) newErrors.name = "Name is required.";
		if (!form.url.trim()) newErrors.url = "Server address is required.";

		if (
			form.authType === "oauth2" &&
			form.oauthClientSecret &&
			!form.oauthClientId
		) {
			newErrors.oauthClientId =
				"Client ID is required when providing a Client Secret.";
		}

		// Non-DCR OAuth: client ID and secret are required
		if (isNonDcrOAuth) {
			if (!form.oauthClientId.trim())
				newErrors.oauthClientId = "Client ID is required.";
			if (!form.oauthClientSecret.trim())
				newErrors.oauthClientSecret = "Client Secret is required.";
		}

		setErrors(newErrors);
		return Object.keys(newErrors).length === 0;
	};

	const handleCreate = async () => {
		if (!validate()) return;

		setIsSubmitting(true);
		try {
			const payload: MCPServerCreate = {
				name: form.name,
				url: form.url,
				authType: form.authType,
				description: form.description || undefined,
				iconUrl: form.iconUrl || undefined,
				apiKey: form.apiKey || undefined,
				oauthClientId: form.oauthClientId || undefined,
				oauthClientSecret: form.oauthClientSecret || undefined,
			};

			const response = await api.post("/mcp-servers", payload);
			addMcpServer(response.data);
			onOpenChange(false);
		} catch {
			console.error("Failed to create MCP server");
		} finally {
			setIsSubmitting(false);
		}
	};

	const handleUpdate = async () => {
		if (!server) return;
		const newErrors: Record<string, string> = {};
		if (!form.name.trim()) newErrors.name = "Name is required.";
		if (!form.url.trim()) newErrors.url = "Server address is required.";
		setErrors(newErrors);
		if (Object.keys(newErrors).length > 0) return;

		setIsSubmitting(true);
		try {
			const payload: MCPServerUpdate = {
				name: form.name,
				url: form.url,
				description: form.description || undefined,
				iconUrl: form.iconUrl || undefined,
			};
			const response = await api.patch(`/mcp-servers/${server.id}`, payload);
			updateMcpServer(server.id, response.data);
			onOpenChange(false);
		} catch {
			console.error("Failed to update MCP server");
		} finally {
			setIsSubmitting(false);
		}
	};

	const handleDelete = async () => {
		if (!server) return;
		if (!window.confirm("Are you sure you want to delete this MCP server?"))
			return;

		setIsSubmitting(true);
		try {
			await api.delete(`/mcp-servers/${server.id}`);
			removeMcpServer(server.id);
			onOpenChange(false);
		} catch (error: unknown) {
			if (
				error instanceof Object &&
				"status" in error &&
				error.status === 403
			) {
				setErrorDialogOpen(true);
			} else {
				console.error("Failed to delete MCP server");
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

		setIsResetting(true);
		try {
			await api.post(`/mcp-servers/${server.id}/reset`);
		} catch (error: unknown) {
			if (
				error instanceof Object &&
				"status" in error &&
				error.status === 403
			) {
				setErrorDialogOpen(true);
			} else {
				console.error("Failed to reset MCP server connections");
			}
		} finally {
			setIsResetting(false);
		}
	};

	const handleOpenChange = (newOpen: boolean) => {
		if (!newOpen) {
			setForm(emptyForm);
			setSelectedOfficial(null);
			setSearchQuery("");
			setErrors({});
		}
		onOpenChange(newOpen);
	};

	const isOfficialIcon = (url?: string) =>
		url ? url.includes(GCS_HOST) : false;

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
						<p className="font-[family-name:var(--font-dm-sans)] text-[14px] text-[#8FA89E] dark:text-muted-foreground font-medium mt-1">
							{isEditMode
								? "Update your server configuration"
								: "Connect a new service to your workspace"}
						</p>
					</div>
					<button
						type="button"
						onClick={() => handleOpenChange(false)}
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
												onClick={() => selectOfficialServer(s)}
												className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-[#F8FAF9] dark:hover:bg-white/5 disabled:opacity-50 disabled:cursor-not-allowed transition-colors cursor-pointer first:rounded-t-[16px] last:rounded-b-[16px]"
											>
												<Image
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
							<label className="block font-[family-name:var(--font-dm-sans)] text-[13px] font-semibold text-[#1E2D28] dark:text-foreground mb-2">
								Name
							</label>
							<SageInput
								placeholder="Server Name"
								value={form.name}
								onChange={(e) => handleFormChange("name", e.target.value)}
								error={!!errors.name}
							/>
							{errors.name && (
								<p className="font-[family-name:var(--font-dm-sans)] text-[13px] text-[#D45B45] mt-1.5">
									{errors.name}
								</p>
							)}
						</div>

						{/* URL */}
						<div>
							<label className="block font-[family-name:var(--font-dm-sans)] text-[13px] font-semibold text-[#1E2D28] dark:text-foreground mb-2">
								Remote Server Address
								<span className="text-[#D45B45] ml-0.5">*</span>
							</label>
							<SageInput
								placeholder="https://mcp.example.com/mcp"
								value={form.url}
								onChange={(e) => handleFormChange("url", e.target.value)}
								error={!!errors.url}
							/>
							{errors.url && (
								<p className="font-[family-name:var(--font-dm-sans)] text-[13px] text-[#D45B45] mt-1.5">
									{errors.url}
								</p>
							)}
						</div>

						{/* Icon URL */}
						<div>
							<label className="block font-[family-name:var(--font-dm-sans)] text-[13px] font-semibold text-[#1E2D28] dark:text-foreground mb-2">
								Icon URL
							</label>
							<SageInput
								placeholder="https://example.com/icon.png"
								value={form.iconUrl}
								onChange={(e) => handleFormChange("iconUrl", e.target.value)}
							/>
						</div>

						{/* Description */}
						<div>
							<label className="block font-[family-name:var(--font-dm-sans)] text-[13px] font-semibold text-[#1E2D28] dark:text-foreground mb-2">
								Description
							</label>
							<SageTextarea
								placeholder="Description"
								value={form.description}
								onChange={(e) =>
									handleFormChange("description", e.target.value)
								}
								rows={4}
							/>
						</div>

						{/* Auth Method */}
						{!isEditMode ? (
							<div>
								<label className="block font-[family-name:var(--font-dm-sans)] text-[13px] font-semibold text-[#1E2D28] dark:text-foreground mb-2">
									Authentication Method
								</label>
								<SageDropdownMenu
									trigger={
										<button className="w-full rounded-full border-[1.5px] border-[#E0E8E4] dark:border-white/10 bg-[#FAFCFB] dark:bg-white/5 text-[14px] font-medium font-[family-name:var(--font-dm-sans)] text-[#1E2D28] dark:text-foreground h-auto py-3 px-[18px] flex items-center justify-between cursor-pointer hover:border-[#A3B5AD] focus:border-[#4CA882] transition-colors outline-none">
											<span>{AUTH_TYPE_LABELS[form.authType]}</span>
											<ChevronDown className="size-4 text-[#8FA89E] shrink-0" />
										</button>
									}
									align="start"
									className="w-(--radix-dropdown-menu-trigger-width)"
									items={[
										{
											label: "None",
											onClick: () => handleFormChange("authType", "none"),
											active: form.authType === "none",
										},
										{
											label: "API Key",
											onClick: () => handleFormChange("authType", "api_key"),
											active: form.authType === "api_key",
										},
										{
											label: "OAuth 2.0",
											onClick: () => handleFormChange("authType", "oauth2"),
											active: form.authType === "oauth2",
										},
									]}
								/>
							</div>
						) : (
							<div>
								<label className="block font-[family-name:var(--font-dm-sans)] text-[13px] font-semibold text-[#1E2D28] dark:text-foreground mb-1">
									Authentication Method
								</label>
								<p className="font-[family-name:var(--font-dm-sans)] text-[14px] text-[#8FA89E] dark:text-muted-foreground font-medium">
									{server?.authType === "none"
										? "None"
										: server?.authType === "api_key"
											? "API Key"
											: "OAuth 2.0"}
								</p>
							</div>
						)}

						{/* API Key field (create only) */}
						{!isEditMode && form.authType === "api_key" && (
							<div>
								<label className="block font-[family-name:var(--font-dm-sans)] text-[13px] font-semibold text-[#1E2D28] dark:text-foreground mb-2">
									API Key
								</label>
								<SageInput
									type="password"
									placeholder="Enter your API Key"
									value={form.apiKey}
									onChange={(e) => handleFormChange("apiKey", e.target.value)}
								/>
							</div>
						)}

						{/* OAuth fields (create only) */}
						{!isEditMode && form.authType === "oauth2" && (
							<div className="space-y-[22px]">
								<p className="font-[family-name:var(--font-dm-sans)] text-[13px] text-[#8FA89E] dark:text-muted-foreground">
									{isNonDcrOAuth
										? "This server requires OAuth credentials."
										: "Leave empty to use Dynamic Client Registration (DCR). Only fill these if your MCP server requires static credentials."}
								</p>
								<div>
									<label className="block font-[family-name:var(--font-dm-sans)] text-[13px] font-semibold text-[#1E2D28] dark:text-foreground mb-2">
										Client ID{isNonDcrOAuth ? "" : " (optional)"}
									</label>
									<SageInput
										placeholder="Enter your OAuth client ID"
										value={form.oauthClientId}
										onChange={(e) =>
											handleFormChange("oauthClientId", e.target.value)
										}
										error={!!errors.oauthClientId}
									/>
									{errors.oauthClientId && (
										<p className="font-[family-name:var(--font-dm-sans)] text-[13px] text-[#D45B45] mt-1.5">
											{errors.oauthClientId}
										</p>
									)}
								</div>
								<div>
									<label className="block font-[family-name:var(--font-dm-sans)] text-[13px] font-semibold text-[#1E2D28] dark:text-foreground mb-2">
										Client Secret{isNonDcrOAuth ? "" : " (optional)"}
									</label>
									<SageInput
										type="password"
										placeholder="Enter your OAuth client secret"
										value={form.oauthClientSecret}
										onChange={(e) =>
											handleFormChange("oauthClientSecret", e.target.value)
										}
										error={!!errors.oauthClientSecret}
									/>
									{errors.oauthClientSecret && (
										<p className="font-[family-name:var(--font-dm-sans)] text-[13px] text-[#D45B45] mt-1.5">
											{errors.oauthClientSecret}
										</p>
									)}
								</div>
							</div>
						)}
					</div>
				</div>

				{/* Footer */}
				<div className="flex items-center px-8 pt-5 pb-6 border-t border-[#F0F3F2] dark:border-white/5">
					{isEditMode ? (
						<>
							<SageButton
								color="destructive-ghost"
								onClick={handleDelete}
								disabled={isSubmitting || isResetting}
							>
								Delete
							</SageButton>
							{server?.authType === "oauth2" && (
								<SageButton
									color="ghost"
									onClick={handleReset}
									disabled={isSubmitting || isResetting}
								>
									{isResetting ? "Resetting..." : "Reset connections"}
								</SageButton>
							)}
							<div className="flex-1" />
							<div className="flex gap-2.5">
								<SageButton
									color="outline"
									onClick={() => handleOpenChange(false)}
								>
									Cancel
								</SageButton>
								<SageButton onClick={handleUpdate} disabled={isSubmitting}>
									{isSubmitting ? "Saving..." : "Save"}
								</SageButton>
							</div>
						</>
					) : (
						<>
							<div className="flex-1" />
							<div className="flex gap-2.5">
								<SageButton
									color="outline"
									onClick={() => handleOpenChange(false)}
								>
									Cancel
								</SageButton>
								<SageButton onClick={handleCreate} disabled={isSubmitting}>
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
