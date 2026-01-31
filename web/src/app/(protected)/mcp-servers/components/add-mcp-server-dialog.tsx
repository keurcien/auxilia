"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api/client";
import { MCPAuthType, MCPServerCreate } from "@/types/mcp-servers";
import { useMcpServersStore } from "@/stores/mcp-servers-store";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
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
import { OfficialMCPServerCard } from "./mcp-server-card";
import { OfficialMCPServer } from "@/types/mcp-servers";

interface AddMCPServerDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
}

export default function AddMCPServerDialog({
	open,
	onOpenChange,
}: AddMCPServerDialogProps) {
	const { addMcpServer } = useMcpServersStore();
	const [activeTab, setActiveTab] = useState("directory");
	const [isSubmitting, setIsSubmitting] = useState(false);
	const [errors, setErrors] = useState<Record<string, string>>({});
	const [officialMCPServers, setOfficialMCPServers] = useState<
		OfficialMCPServer[]
	>([]);

	const [customForm, setCustomForm] = useState({
		name: "",
		url: "",
		description: "",
		authType: "none" as MCPAuthType,
		apiKey: "",
		oauthClientId: "",
		oauthClientSecret: "",
	});

	const validateCustomForm = () => {
		const newErrors: Record<string, string> = {};

		if (!customForm.name.trim()) {
			newErrors.name = "Name is required.";
		}

		if (!customForm.url.trim()) {
			newErrors.url = "Server address is required.";
		}

		// OAuth validation: can't have client secret without client id
		if (
			customForm.authType === "oauth2" &&
			customForm.oauthClientSecret &&
			!customForm.oauthClientId
		) {
			newErrors.oauthClientId =
				"Client ID is required when providing a Client Secret.";
		}

		setErrors(newErrors);
		return Object.keys(newErrors).length === 0;
	};

	const handleCustomSubmit = async (e: React.FormEvent) => {
		e.preventDefault();

		if (!validateCustomForm()) {
			return;
		}

		setIsSubmitting(true);
		try {
			const payload: MCPServerCreate = {
				name: customForm.name,
				url: customForm.url,
				authType: customForm.authType,
				description: customForm.description || undefined,
				apiKey: customForm.apiKey || undefined,
				oauthClientId: customForm.oauthClientId || undefined,
				oauthClientSecret: customForm.oauthClientSecret || undefined,
			};

			const response = await api.post("/mcp-servers", payload);

			// Add the newly created server to the store
			addMcpServer(response.data);

			setCustomForm({
				name: "",
				url: "",
				description: "",
				authType: "none",
				apiKey: "",
				oauthClientId: "",
				oauthClientSecret: "",
			});
			setErrors({});

			fetchOfficialServers();
			onOpenChange(false);
		} catch (error) {
			console.error("Failed to create MCP server:", error);
		} finally {
			setIsSubmitting(false);
		}
	};

	const handleCustomFormChange = (
		field: keyof typeof customForm,
		value: string | boolean,
	) => {
		setCustomForm((prev) => ({ ...prev, [field]: value }));
		if (errors[field]) {
			setErrors((prev) => {
				const newErrors = { ...prev };
				delete newErrors[field];
				return newErrors;
			});
		}
	};

	const fetchOfficialServers = () => {
		api
			.get("/mcp-servers/official")
			.then((res) => setOfficialMCPServers(res.data));
	};

	useEffect(() => {
		fetchOfficialServers();
	}, []);

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent
				className="sm:max-w-[600px] min-h-[600px] max-h-[800px]"
				showCloseButton={false}
			>
				<div className="relative flex h-full flex-col overflow-auto min-h-0 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden p-1">
					<Tabs
						value={activeTab}
						onValueChange={setActiveTab}
						className="w-full"
					>
						<TabsList className="grid w-full grid-cols-2">
							<TabsTrigger value="directory">Official MCP Servers</TabsTrigger>
							<TabsTrigger value="custom">Custom MCP Server</TabsTrigger>
						</TabsList>

						<TabsContent value="directory" className="space-y-4">
							<div className="py-8 text-muted-foreground">
								<div className="grid grid-cols-2 gap-x-2.5 gap-y-2 mx-0">
									{officialMCPServers.map((server) => (
										<OfficialMCPServerCard
											key={server.name}
											server={server}
											onInstall={() => {
												fetchOfficialServers();
											}}
										/>
									))}
								</div>
							</div>
						</TabsContent>

						<TabsContent value="custom" className="space-y-4">
							<form onSubmit={handleCustomSubmit} className="space-y-6">
								<div>
									<div className="flex items-center gap-3">
										<div className="flex-1">
											<Label htmlFor="name">Server Name</Label>
											<Input
												id="name"
												placeholder="Server Name"
												value={customForm.name}
												onChange={(e) =>
													handleCustomFormChange("name", e.target.value)
												}
												className={errors.name ? "border-red-500" : ""}
												aria-invalid={!!errors.name}
											/>
										</div>
									</div>
									{errors.name && (
										<p className="text-sm text-red-600 flex items-center gap-1.5">
											{errors.name}
										</p>
									)}
								</div>

								<div>
									<Label htmlFor="url">
										Remote Server Address<span className="text-red-600">*</span>
									</Label>
									<Input
										id="url"
										placeholder="https://mcp.example.com/mcp"
										value={customForm.url}
										onChange={(e) =>
											handleCustomFormChange("url", e.target.value)
										}
										className={errors.url ? "border-red-500" : ""}
										aria-invalid={!!errors.url}
									/>
									{errors.url && (
										<p className="text-sm text-red-600">{errors.url}</p>
									)}
								</div>

								<div className="space-y-2">
									<Label htmlFor="description">Description</Label>
									<Textarea
										id="description"
										placeholder="Description"
										value={customForm.description}
										onChange={(e) =>
											handleCustomFormChange("description", e.target.value)
										}
										className="min-h-[80px]"
									/>
								</div>

								<div className="space-y-2">
									<Label htmlFor="authType">Authentication Method</Label>
									<Select
										value={customForm.authType}
										onValueChange={(value) =>
											handleCustomFormChange("authType", value)
										}
									>
										<SelectTrigger id="authType" className="w-full">
											<SelectValue placeholder="Select authentication method" />
										</SelectTrigger>
										<SelectContent>
											<SelectItem value="none">None</SelectItem>
											<SelectItem value="api_key">API Key</SelectItem>
											<SelectItem value="oauth2">OAuth 2.0</SelectItem>
										</SelectContent>
									</Select>
								</div>

								{customForm.authType === "api_key" && (
									<div className="space-y-2">
										<Label htmlFor="apiKey">API Key</Label>
										<Input
											id="apiKey"
											type="password"
											placeholder="Enter your API Key"
											value={customForm.apiKey}
											onChange={(e) =>
												handleCustomFormChange("apiKey", e.target.value)
											}
										/>
									</div>
								)}

								{customForm.authType === "oauth2" && (
									<div className="space-y-4">
										<p className="text-sm text-muted-foreground">
											Leave empty to use Dynamic Client Registration (DCR). Only
											fill these if your MCP server requires static credentials.
										</p>
										<div className="space-y-2">
											<Label htmlFor="oauthClientId">
												Client ID (optional)
											</Label>
											<Input
												id="oauthClientId"
												placeholder="Enter your OAuth client ID"
												value={customForm.oauthClientId}
												onChange={(e) =>
													handleCustomFormChange(
														"oauthClientId",
														e.target.value,
													)
												}
												className={errors.oauthClientId ? "border-red-500" : ""}
												aria-invalid={!!errors.oauthClientId}
											/>
											{errors.oauthClientId && (
												<p className="text-sm text-red-600">
													{errors.oauthClientId}
												</p>
											)}
										</div>
										<div className="space-y-2">
											<Label htmlFor="oauthClientSecret">
												Client Secret (optional)
											</Label>
											<Input
												id="oauthClientSecret"
												type="password"
												placeholder="Enter your OAuth client secret"
												value={customForm.oauthClientSecret}
												onChange={(e) =>
													handleCustomFormChange(
														"oauthClientSecret",
														e.target.value,
													)
												}
											/>
										</div>
									</div>
								)}

								<div className="flex justify-end gap-3 pt-2">
									<Button type="submit" disabled={isSubmitting}>
										{isSubmitting ? "Creating..." : "Create"}
									</Button>
								</div>
							</form>
						</TabsContent>
					</Tabs>
				</div>
			</DialogContent>
		</Dialog>
	);
}
