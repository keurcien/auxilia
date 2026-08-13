"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Eye, EyeOff, ShieldCheck } from "lucide-react";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import { SageAlert } from "@/components/ui/sage-alert";
import { api } from "@/lib/api/client";
import { getApiErrorMessage } from "@/lib/api/errors";
import { useMcpServersStore } from "@/stores/mcp-servers-store";
import { MCPAuthType, OfficialMCPServer } from "@/types/mcp-servers";
import { ConnectionTestBanner } from "../../components/connection-test-banner";
import {
	HeaderButton,
	HeaderPrimaryButton,
	SubpageHeader,
} from "@/components/layout/subpage-header";
import {
	buildMCPServerCreatePayload,
	MCPServerCreateFormErrors,
	MCPServerCreateFormValues,
	requiresStaticOAuthCredentials,
	validateMCPServerCreateForm,
} from "../../lib/mcp-server-create-form";
import { useConnectionTest } from "../../lib/use-connection-test";

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

const LABEL_CLASS = "text-[13px] font-semibold text-foreground";
const OPTIONAL_HINT = (
	<span className="font-normal text-meta dark:text-panel-dim"> optional</span>
);
const INPUT_CLASS =
	"w-full rounded-lg border border-input bg-card px-3 py-[9px] text-[13.5px] font-medium text-foreground outline-none transition-[border-color,box-shadow] placeholder:text-meta dark:placeholder:text-panel-dim focus:border-petrol focus:shadow-[0_0_0_3px_rgba(22,96,110,0.10)]";
const MONO_INPUT_CLASS = `${INPUT_CLASS} font-mono text-[12.5px] font-normal`;
const ERROR_CLASS = "text-[12.5px] text-destructive";

const AUTH_OPTIONS: {
	value: MCPAuthType;
	label: string;
	description: string;
}[] = [
	{ value: "none", label: "None", description: "Open endpoint, no credentials." },
	{
		value: "api_key",
		label: "API key",
		description: "One shared key for the whole workspace.",
	},
	{
		value: "oauth2",
		label: "OAuth 2.0",
		description: "Each user connects their own account.",
	},
];

function AuthMethodCards({
	value,
	onChange,
}: {
	value: MCPAuthType;
	onChange: (value: MCPAuthType) => void;
}) {
	return (
		<div
			role="radiogroup"
			aria-label="Authentication method"
			className="grid grid-cols-1 gap-2.5 sm:grid-cols-3"
		>
			{AUTH_OPTIONS.map((option) => {
				const selected = option.value === value;
				return (
					<button
						key={option.value}
						type="button"
						role="radio"
						aria-checked={selected}
						onClick={() => {
							onChange(option.value);
						}}
						className={`flex cursor-pointer flex-col gap-[5px] rounded-[10px] border p-[13px] text-left transition-[border-color,box-shadow] ${
							selected
								? "border-petrol bg-[#F7FAFA] shadow-[0_0_0_3px_rgba(22,96,110,0.08)] dark:bg-petrol/10"
								: "border-border hover:border-input"
						}`}
					>
						<span className="flex items-center gap-2">
							<span
								className={`flex size-3.5 shrink-0 items-center justify-center rounded-full border-[1.5px] ${
									selected ? "border-petrol" : "border-faint"
								}`}
							>
								{selected && (
									<span className="size-[7px] rounded-full bg-petrol" />
								)}
							</span>
							<span className="text-[13px] font-semibold text-foreground">
								{option.label}
							</span>
						</span>
						<span
							className={`text-[11.5px] leading-[1.45] ${
								selected
									? "text-body dark:text-panel-body"
									: "text-meta dark:text-panel-dim"
							}`}
						>
							{option.description}
						</span>
					</button>
				);
			})}
		</div>
	);
}

export default function CustomMCPServerPage() {
	const router = useRouter();
	const searchParams = useSearchParams();
	const officialId = searchParams.get("official");
	const createMcpServer = useMcpServersStore((state) => state.createMcpServer);

	const [form, setForm] = useState<MCPServerCreateFormValues>(emptyForm);
	const [errors, setErrors] = useState<MCPServerCreateFormErrors>({});
	const [selectedOfficial, setSelectedOfficial] =
		useState<OfficialMCPServer | null>(null);
	const [submitError, setSubmitError] = useState<string | null>(null);
	const [isSubmitting, setIsSubmitting] = useState(false);
	const [showSecret, setShowSecret] = useState(false);
	const [forbiddenOpen, setForbiddenOpen] = useState(false);

	const { status: testStatus, message: testMessage, reset: resetTest, runCandidateTest } =
		useConnectionTest();

	// Arriving from a catalog card that needs static OAuth credentials: prefill
	// the form with the official entry.
	useEffect(() => {
		if (!officialId) return;
		const controller = new AbortController();
		void (async () => {
			try {
				const res = await api.get<OfficialMCPServer[]>("/mcp-servers/official", {
					signal: controller.signal,
				});
				const official = res.data.find((server) => server.id === officialId);
				if (!official) return;
				setSelectedOfficial(official);
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
			} catch {
				// Aborted or catalog unavailable — the blank form still works.
			}
		})();
		return () => {
			controller.abort();
		};
	}, [officialId]);

	const isNonDcrOAuth = requiresStaticOAuthCredentials(selectedOfficial);

	const handleFormChange = (
		field: keyof MCPServerCreateFormValues,
		value: string,
	) => {
		setForm((prev) => ({ ...prev, [field]: value }));
		// Editing a field clears its error (rebuild without the key — no
		// dynamic access/delete, which static analysis flags as injection).
		setErrors((prev) =>
			Object.fromEntries(
				Object.entries(prev).filter(([key]) => key !== field),
			) as MCPServerCreateFormErrors,
		);
		// A prior test result no longer reflects the edited config.
		if (testStatus !== "idle") resetTest();
	};

	const handleCreate = async () => {
		const newErrors = validateMCPServerCreateForm(form, selectedOfficial);
		setErrors(newErrors);
		if (Object.keys(newErrors).length > 0) return;

		setSubmitError(null);
		setIsSubmitting(true);
		try {
			await createMcpServer(buildMCPServerCreatePayload(form));
			router.push("/mcp-servers");
		} catch (error: unknown) {
			if (error instanceof Object && "status" in error && error.status === 403) {
				setForbiddenOpen(true);
			} else {
				setSubmitError(getApiErrorMessage(error, "Failed to create MCP server."));
			}
		} finally {
			setIsSubmitting(false);
		}
	};

	const handleTest = () => {
		if (!form.url.trim()) {
			setErrors((prev) => ({ ...prev, url: "Server address is required." }));
			return;
		}
		void runCandidateTest({
			url: form.url,
			authType: form.authType,
			apiKey: form.apiKey,
		});
	};

	const canSubmit = Boolean(form.url.trim() && form.name.trim());

	return (
		<div className="flex h-svh min-w-0 flex-1 flex-col bg-background animate-in fade-in duration-300">
			<SubpageHeader
				trail={[
					{ label: "workspace" },
					{ label: "mcp-servers", href: "/mcp-servers" },
					{ label: "add", href: "/mcp-servers/add" },
					{ label: "custom" },
				]}
			>
				<HeaderButton
					disabled={isSubmitting}
					onClick={() => {
						router.push("/mcp-servers");
					}}
				>
					Cancel
				</HeaderButton>
				<HeaderPrimaryButton
					disabled={!canSubmit || isSubmitting}
					onClick={() => {
						void handleCreate();
					}}
				>
					{isSubmitting ? "Adding…" : "Add server"}
				</HeaderPrimaryButton>
			</SubpageHeader>

			<div className="min-h-0 flex-1 overflow-y-auto px-4 py-8 sm:px-9 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
				<div className="mx-auto max-w-[640px]">
					<Link
						href="/mcp-servers/add"
						className="text-[13px] font-semibold text-petrol hover:underline"
					>
						‹ Catalog
					</Link>
					<h1 className="mt-3.5 font-display text-[26px] font-bold tracking-[-0.03em] text-foreground">
						{selectedOfficial ? `Add ${selectedOfficial.name}` : "Custom MCP server"}
					</h1>
					<p className="mt-2 text-[14px] leading-[1.6] text-body dark:text-panel-body text-pretty">
						{/* Gate on the ACTIVE auth method — the catalog hint must not
						    outlive a switch to another method. */}
						{isNonDcrOAuth && form.authType === "oauth2"
							? "This server requires OAuth credentials from the provider's developer console."
							: selectedOfficial?.authType === "api_key" &&
								  form.authType === "api_key"
								? "This server requires an API key shared by the whole workspace."
								: "Connect any remote server that speaks the Model Context Protocol over HTTP."}
					</p>

					<div className="mt-7 flex flex-col gap-[18px]">
						{/* Remote server address */}
						<div className="flex flex-col gap-[7px]">
							<label htmlFor="mcp-url" className={LABEL_CLASS}>
								Remote server address <span className="text-destructive">*</span>
							</label>
							<input
								id="mcp-url"
								placeholder="https://mcp.example.com/v1"
								value={form.url}
								onChange={(e) => {
									handleFormChange("url", e.target.value);
								}}
								aria-required="true"
								aria-invalid={!!errors.url}
								aria-describedby={errors.url ? "mcp-url-error" : undefined}
								className={MONO_INPUT_CLASS}
							/>
							{errors.url ? (
								<span id="mcp-url-error" className={ERROR_CLASS}>
									{errors.url}
								</span>
							) : (
								<span className="text-[12px] text-meta dark:text-panel-dim">
									Streamable HTTP endpoint — the only transport auxilia supports.
								</span>
							)}
						</div>

						{/* Name + Icon URL */}
						<div className="flex flex-col gap-[18px] sm:flex-row sm:gap-3.5">
							<div className="flex flex-1 flex-col gap-[7px]">
								<label htmlFor="mcp-name" className={LABEL_CLASS}>
									Name <span className="text-destructive">*</span>
								</label>
								<input
									id="mcp-name"
									placeholder="e.g. Internal warehouse"
									value={form.name}
									onChange={(e) => {
										handleFormChange("name", e.target.value);
									}}
									aria-required="true"
									aria-invalid={!!errors.name}
									aria-describedby={errors.name ? "mcp-name-error" : undefined}
									className={INPUT_CLASS}
								/>
								{errors.name && (
									<span id="mcp-name-error" className={ERROR_CLASS}>
										{errors.name}
									</span>
								)}
							</div>
							<div className="flex flex-1 flex-col gap-[7px]">
								<label htmlFor="mcp-icon-url" className={LABEL_CLASS}>
									Icon URL{OPTIONAL_HINT}
								</label>
								<input
									id="mcp-icon-url"
									placeholder="https://…/icon.svg"
									value={form.iconUrl}
									onChange={(e) => {
										handleFormChange("iconUrl", e.target.value);
									}}
									className={MONO_INPUT_CLASS}
								/>
							</div>
						</div>

						{/* Description */}
						<div className="flex flex-col gap-[7px]">
							<label htmlFor="mcp-description" className={LABEL_CLASS}>
								Description{OPTIONAL_HINT}
							</label>
							<textarea
								id="mcp-description"
								rows={3}
								placeholder="What agents can do with this server — shown in the servers list and the agent editor."
								value={form.description}
								onChange={(e) => {
									handleFormChange("description", e.target.value);
								}}
								className={`${INPUT_CLASS} resize-none leading-[1.55]`}
							/>
						</div>

						{/* Authentication method */}
						<div className="flex flex-col gap-2.5">
							<span className={LABEL_CLASS}>Authentication method</span>
							<AuthMethodCards
								value={form.authType}
								onChange={(value) => {
									handleFormChange("authType", value);
								}}
							/>
						</div>

						{/* API key panel */}
						{form.authType === "api_key" && (
							<div className="flex flex-col gap-[18px] rounded-xl border border-border bg-sidebar p-[18px] dark:bg-white/5">
								<div className="text-[12.5px] leading-[1.55] text-subtle dark:text-panel-body">
									The key is encrypted at rest and shared by everyone in the
									workspace — it is never shown again after saving.
								</div>
								<div className="flex flex-col gap-[7px]">
									<label htmlFor="mcp-api-key" className={LABEL_CLASS}>
										API key <span className="text-destructive">*</span>
									</label>
									<input
										id="mcp-api-key"
										type="password"
										placeholder="Enter your API key"
										value={form.apiKey}
										onChange={(e) => {
											handleFormChange("apiKey", e.target.value);
										}}
										aria-required="true"
										aria-invalid={!!errors.apiKey}
										aria-describedby={
											errors.apiKey ? "mcp-api-key-error" : undefined
										}
										className={MONO_INPUT_CLASS}
									/>
									{errors.apiKey && (
										<span id="mcp-api-key-error" className={ERROR_CLASS}>
											{errors.apiKey}
										</span>
									)}
								</div>
							</div>
						)}

						{/* OAuth panel */}
						{form.authType === "oauth2" && (
							<div className="flex flex-col gap-[18px] rounded-xl border border-border bg-sidebar p-[18px] dark:bg-white/5">
								<div className="text-[12.5px] leading-[1.55] text-subtle dark:text-panel-body">
									{isNonDcrOAuth ? (
										"This server requires a static Client ID and secret from the provider's developer console."
									) : (
										<>
											Provide a Client ID and secret from the provider&apos;s
											developer console — or leave both blank to use{" "}
											<strong className="text-body dark:text-panel-body">
												Dynamic Client Registration
											</strong>{" "}
											if the server supports it.
										</>
									)}
								</div>
								<div className="flex flex-col gap-[7px]">
									<label htmlFor="mcp-oauth-client-id" className={LABEL_CLASS}>
										Client ID{isNonDcrOAuth ? "" : OPTIONAL_HINT}
									</label>
									<input
										id="mcp-oauth-client-id"
										placeholder="client_xxxxxxxx"
										value={form.oauthClientId}
										onChange={(e) => {
											handleFormChange("oauthClientId", e.target.value);
										}}
										aria-required={isNonDcrOAuth}
										aria-invalid={!!errors.oauthClientId}
										aria-describedby={
											errors.oauthClientId
												? "mcp-oauth-client-id-error"
												: undefined
										}
										className={MONO_INPUT_CLASS}
									/>
									{errors.oauthClientId && (
										<span id="mcp-oauth-client-id-error" className={ERROR_CLASS}>
											{errors.oauthClientId}
										</span>
									)}
								</div>
								<div className="flex flex-col gap-[7px]">
									<label htmlFor="mcp-oauth-client-secret" className={LABEL_CLASS}>
										Client secret
										{isNonDcrOAuth ? (
											""
										) : (
											<span className="font-normal text-meta dark:text-panel-dim">
												{" "}
												optional · write-only
											</span>
										)}
									</label>
									<div className="relative">
										<input
											id="mcp-oauth-client-secret"
											type={showSecret ? "text" : "password"}
											placeholder="••••••••••••"
											value={form.oauthClientSecret}
											onChange={(e) => {
												handleFormChange("oauthClientSecret", e.target.value);
											}}
											aria-required={isNonDcrOAuth}
											aria-invalid={!!errors.oauthClientSecret}
											aria-describedby={
												errors.oauthClientSecret
													? "mcp-oauth-client-secret-error"
													: undefined
											}
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
									{errors.oauthClientSecret && (
										<span
											id="mcp-oauth-client-secret-error"
											className={ERROR_CLASS}
										>
											{errors.oauthClientSecret}
										</span>
									)}
								</div>
							</div>
						)}

						{/* Test before adding */}
						<div className="flex items-center gap-3 rounded-xl border border-border p-[15px] pl-[18px]">
							<span className="flex size-[34px] shrink-0 items-center justify-center rounded-[9px] bg-petrol-tint text-petrol">
								<ShieldCheck className="size-4" />
							</span>
							<span className="min-w-0 flex-1">
								<span className="block text-[13.5px] font-semibold text-foreground">
									Test before adding
								</span>
								<span className="mt-px block text-[12px] text-subtle dark:text-panel-dim">
									Checks the endpoint responds, auth works, and lists the tools
									it exposes.
								</span>
							</span>
							<HeaderButton
								accent
								disabled={testStatus === "testing" || !form.url.trim()}
								onClick={handleTest}
							>
								{testStatus === "testing" ? "Testing…" : "Test connection"}
							</HeaderButton>
						</div>

						<ConnectionTestBanner status={testStatus} message={testMessage} />

						{submitError && (
							<SageAlert key={submitError} variant="error" message={submitError} />
						)}
					</div>
				</div>
			</div>

			<ForbiddenErrorDialog
				open={forbiddenOpen}
				onOpenChange={setForbiddenOpen}
				title="Insufficient privileges"
				message="You need admin permissions to add MCP servers."
			/>
		</div>
	);
}
