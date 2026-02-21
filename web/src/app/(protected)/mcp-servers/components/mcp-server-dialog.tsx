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
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { Search, X, CheckIcon } from "lucide-react";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import Image from "next/image";

const DEFAULT_ICON = "https://storage.googleapis.com/choose-assets/mcp.png";
const GCS_HOST = "storage.googleapis.com";

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
				className="sm:max-w-[560px] rounded-3xl p-0 gap-0 overflow-hidden"
				showCloseButton={false}
			>
				{/* ── Header ── */}
				<div className="flex items-center justify-between px-8 pt-6 pb-5 border-b border-border">
					<div>
						<h2 className="text-lg font-bold tracking-tight">
							{isEditMode ? "Edit MCP Server" : "Add MCP Server"}
						</h2>
						<p className="text-[13px] text-muted-foreground mt-1">
							{isEditMode
								? "Update your server configuration"
								: "Connect a new service to your workspace"}
						</p>
					</div>
					<button
						type="button"
						onClick={() => handleOpenChange(false)}
						className="flex items-center justify-center w-8 h-8 rounded-[10px] bg-muted text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
					>
						<X className="w-4 h-4" />
					</button>
				</div>

				{/* ── Content ── */}
				<div className="px-8 pt-6 pb-2 max-h-[60vh] overflow-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
					{/* Create Mode: ConnectorSearch */}
					{!isEditMode && (
						<div className="mb-6">
							{selectedOfficial ? (
								<div className="flex items-center gap-3 rounded-xl border border-border px-3.5 py-2.5">
									<Image
										src={selectedOfficial.iconUrl ?? DEFAULT_ICON}
										alt={selectedOfficial.name}
										width={24}
										height={24}
										className="shrink-0 rounded-md"
									/>
									<span className="text-sm font-medium flex-1">
										{selectedOfficial.name}
									</span>
									<button
										type="button"
										onClick={clearSelection}
										className="text-muted-foreground hover:text-foreground transition-colors"
									>
										<X className="w-4 h-4" />
									</button>
								</div>
							) : (
								<div className="relative">
									<Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
									<Input
										placeholder="Search official MCP servers..."
										value={searchQuery}
										onChange={(e) => setSearchQuery(e.target.value)}
										className="pl-10 rounded-xl"
									/>
								</div>
							)}

							{/* Dropdown list of official servers */}
							{!selectedOfficial && (
								<div className="mt-2 max-h-[200px] overflow-auto rounded-xl border border-border [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
									{filteredServers.length === 0 ? (
										<div className="p-3 text-sm text-muted-foreground text-center">
											No servers found
										</div>
									) : (
										filteredServers.map((s) => (
											<button
												key={s.name}
												type="button"
												disabled={s.isInstalled}
												onClick={() => selectOfficialServer(s)}
												className="flex w-full items-center gap-3 px-3.5 py-2.5 text-left hover:bg-muted/50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
											>
												<Image
													src={s.iconUrl ?? DEFAULT_ICON}
													alt={s.name}
													width={24}
													height={24}
													className="shrink-0 rounded-md"
												/>
												<span className="text-sm font-medium flex-1 truncate">
													{s.name}
												</span>
												{s.isInstalled && (
													<CheckIcon
														className="w-4 h-4 text-emerald-500"
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

					{/* Edit Mode: EditHeader */}
					{isEditMode && server && (
						<div className="flex items-center gap-3.5 p-4 rounded-xl bg-muted border border-border mb-6">
							<Image
								src={server.iconUrl ?? DEFAULT_ICON}
								alt={server.name}
								width={40}
								height={40}
								className="shrink-0 rounded-lg"
							/>
							<div className="min-w-0 flex-1">
								<div className="flex items-center gap-2">
									<h3 className="font-semibold text-sm truncate">
										{server.name}
									</h3>
									{isOfficialIcon(server.iconUrl) && (
										<span className="text-[11px] font-semibold text-primary bg-primary/10 px-2 py-0.5 rounded-full tracking-wide">
											Official
										</span>
									)}
								</div>
								<p className="text-xs text-muted-foreground truncate mt-0.5">
									{server.url}
								</p>
							</div>
						</div>
					)}

					{/* ── Shared Form ── */}
					<div className="space-y-5 mb-4">
						<div className="space-y-1.5">
							<Label htmlFor="name" className="text-[13px] font-semibold">
								Name
							</Label>
							<Input
								id="name"
								placeholder="Server Name"
								value={form.name}
								onChange={(e) => handleFormChange("name", e.target.value)}
								className={`rounded-xl ${errors.name ? "border-red-500" : ""}`}
								aria-invalid={!!errors.name}
							/>
							{errors.name && (
								<p className="text-sm text-red-600 mt-1">{errors.name}</p>
							)}
						</div>

						<div className="space-y-1.5">
							<Label htmlFor="url" className="text-[13px] font-semibold">
								Remote Server Address
								<span className="text-red-600">*</span>
							</Label>
							<Input
								id="url"
								placeholder="https://mcp.example.com/mcp"
								value={form.url}
								onChange={(e) => handleFormChange("url", e.target.value)}
								className={`rounded-xl ${errors.url ? "border-red-500" : ""}`}
								aria-invalid={!!errors.url}
							/>
							{errors.url && (
								<p className="text-sm text-red-600 mt-1">{errors.url}</p>
							)}
						</div>

						<div className="space-y-1.5">
							<Label htmlFor="iconUrl" className="text-[13px] font-semibold">
								Icon URL
							</Label>
							<Input
								id="iconUrl"
								placeholder="https://example.com/icon.png"
								value={form.iconUrl}
								onChange={(e) => handleFormChange("iconUrl", e.target.value)}
								className="rounded-xl"
							/>
						</div>

						<div className="space-y-1.5">
							<Label
								htmlFor="description"
								className="text-[13px] font-semibold"
							>
								Description
							</Label>
							<Textarea
								id="description"
								placeholder="Description"
								value={form.description}
								onChange={(e) =>
									handleFormChange("description", e.target.value)
								}
								className="min-h-[80px] rounded-xl md:text-sm"
							/>
						</div>

						{/* Auth Method: editable in create, read-only in edit */}
						{!isEditMode ? (
							<div className="space-y-1.5">
								<Label htmlFor="authType" className="text-[13px] font-semibold">
									Authentication Method
								</Label>
								<Select
									value={form.authType}
									onValueChange={(value) => handleFormChange("authType", value)}
								>
									<SelectTrigger id="authType" className="w-full rounded-xl">
										<SelectValue placeholder="Select authentication method" />
									</SelectTrigger>
									<SelectContent>
										<SelectItem value="none">None</SelectItem>
										<SelectItem value="api_key">API Key</SelectItem>
										<SelectItem value="oauth2">OAuth 2.0</SelectItem>
									</SelectContent>
								</Select>
							</div>
						) : (
							<div className="space-y-1.5">
								<Label className="text-[13px] font-semibold">
									Authentication Method
								</Label>
								<p className="text-sm text-muted-foreground">
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
							<div className="space-y-1.5">
								<Label htmlFor="apiKey" className="text-[13px] font-semibold">
									API Key
								</Label>
								<Input
									id="apiKey"
									type="password"
									placeholder="Enter your API Key"
									value={form.apiKey}
									onChange={(e) => handleFormChange("apiKey", e.target.value)}
									className="rounded-xl"
								/>
							</div>
						)}

						{/* OAuth fields (create only) */}
						{!isEditMode && form.authType === "oauth2" && (
							<div className="space-y-4">
								{isNonDcrOAuth ? (
									<p className="text-sm text-muted-foreground">
										This server requires OAuth credentials.
									</p>
								) : (
									<p className="text-sm text-muted-foreground">
										Leave empty to use Dynamic Client Registration (DCR). Only
										fill these if your MCP server requires static credentials.
									</p>
								)}
								<div className="space-y-1.5">
									<Label
										htmlFor="oauthClientId"
										className="text-[13px] font-semibold"
									>
										Client ID{isNonDcrOAuth ? "" : " (optional)"}
									</Label>
									<Input
										id="oauthClientId"
										placeholder="Enter your OAuth client ID"
										value={form.oauthClientId}
										onChange={(e) =>
											handleFormChange("oauthClientId", e.target.value)
										}
										className={`rounded-xl ${errors.oauthClientId ? "border-red-500" : ""}`}
										aria-invalid={!!errors.oauthClientId}
									/>
									{errors.oauthClientId && (
										<p className="text-sm text-red-600">
											{errors.oauthClientId}
										</p>
									)}
								</div>
								<div className="space-y-1.5">
									<Label
										htmlFor="oauthClientSecret"
										className="text-[13px] font-semibold"
									>
										Client Secret{isNonDcrOAuth ? "" : " (optional)"}
									</Label>
									<Input
										id="oauthClientSecret"
										type="password"
										placeholder="Enter your OAuth client secret"
										value={form.oauthClientSecret}
										onChange={(e) =>
											handleFormChange("oauthClientSecret", e.target.value)
										}
										className={`rounded-xl ${errors.oauthClientSecret ? "border-red-500" : ""}`}
										aria-invalid={!!errors.oauthClientSecret}
									/>
									{errors.oauthClientSecret && (
										<p className="text-sm text-red-600">
											{errors.oauthClientSecret}
										</p>
									)}
								</div>
							</div>
						)}
					</div>
				</div>

				{/* ── Footer ── */}
				<div className="flex items-center px-8 pt-4 pb-6 border-t border-border">
					{isEditMode ? (
						<>
							<Button
								variant="ghost"
								onClick={handleDelete}
								disabled={isSubmitting}
								className="text-destructive hover:text-destructive hover:bg-destructive/10 rounded-xl text-[13px] font-semibold cursor-pointer"
							>
								Delete server
							</Button>
							<div className="flex-1" />
							<div className="flex gap-2.5">
								<Button
									variant="outline"
									onClick={() => handleOpenChange(false)}
									className="rounded-xl cursor-pointer"
								>
									Cancel
								</Button>
								<Button
									onClick={handleUpdate}
									disabled={isSubmitting}
									className="rounded-xl cursor-pointer"
								>
									{isSubmitting ? "Saving..." : "Save changes"}
								</Button>
							</div>
						</>
					) : (
						<>
							<div className="flex-1" />
							<div className="flex gap-2.5">
								<Button
									variant="outline"
									onClick={() => handleOpenChange(false)}
									className="rounded-xl cursor-pointer"
								>
									Cancel
								</Button>
								<Button
									onClick={handleCreate}
									disabled={isSubmitting}
									className="rounded-xl cursor-pointer"
								>
									{isSubmitting ? "Creating..." : "Create server"}
								</Button>
							</div>
						</>
					)}
				</div>
			</DialogContent>
		</Dialog>
	);
}
