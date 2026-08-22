"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import { SANDBOX_PROVIDER_ICONS } from "@/lib/sandbox-providers";
import {
	Dialog,
	DialogButton,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api/client";
import type {
	Sandbox,
	SandboxProviderType,
	SandboxSecretHint,
} from "@/types/sandboxes";

interface ProviderSpec {
	label: string;
	secretLabel: string;
	secretRequired: boolean;
	urlLabel: string;
	urlPlaceholder: string;
	defaultUrl?: string;
}

export const SANDBOX_PROVIDER_SPECS: Record<SandboxProviderType, ProviderSpec> =
	{
		opensandbox: {
			label: "OpenSandbox",
			secretLabel: "API key",
			secretRequired: false,
			urlLabel: "Domain",
			urlPlaceholder: "sandbox.example.com",
		},
		cloudrun: {
			label: "Cloud Run",
			secretLabel: "Gateway secret",
			secretRequired: true,
			urlLabel: "Gateway URL",
			urlPlaceholder: "https://sandbox-gateway-xxxx.run.app",
		},
		daytona: {
			label: "Daytona",
			secretLabel: "API key",
			secretRequired: true,
			urlLabel: "API URL",
			urlPlaceholder: "https://app.daytona.io/api",
			defaultUrl: "https://app.daytona.io/api",
		},
	};

const PROVIDER_ORDER: SandboxProviderType[] = [
	"opensandbox",
	"cloudrun",
	"daytona",
];

interface SandboxFormState {
	provider: SandboxProviderType;
	name: string;
	description: string;
	url: string;
	secret: string;
	defaultPackages: string;
	timeout: string;
	// opensandbox
	defaultImage: string;
	volumeMounts: string;
	useServerProxy: boolean;
	// cloudrun
	gcsBucket: string;
	snapshotPrefix: string;
	allowEgress: boolean;
	// daytona
	target: string;
	snapshot: string;
	autoStopInterval: string;
}

const defaultForm = (): SandboxFormState => ({
	provider: "opensandbox",
	name: "",
	description: "",
	url: "",
	secret: "",
	defaultPackages: "",
	timeout: "1800",
	defaultImage: "python:3.12-slim",
	volumeMounts: "",
	useServerProxy: true,
	gcsBucket: "",
	snapshotPrefix: "sandbox-snapshots/",
	allowEgress: false,
	target: "us",
	snapshot: "",
	autoStopInterval: "15",
});

const str = (value: unknown, fallback: string): string =>
	typeof value === "string" ? value : fallback;

const num = (value: unknown, fallback: string): string =>
	typeof value === "number" ? String(value) : fallback;

const list = (value: unknown): string =>
	Array.isArray(value) ? value.join(", ") : "";

const bool = (value: unknown, fallback: boolean): boolean =>
	typeof value === "boolean" ? value : fallback;

const fromSandbox = (sandbox: Sandbox): SandboxFormState => {
	const base = defaultForm();
	const config = sandbox.config;
	return {
		...base,
		provider: sandbox.provider,
		name: sandbox.name,
		description: sandbox.description ?? "",
		url: sandbox.url,
		defaultPackages: list(config.defaultPackages),
		timeout: num(config.timeout, base.timeout),
		defaultImage: str(config.defaultImage, base.defaultImage),
		volumeMounts: list(config.volumeMounts),
		useServerProxy: bool(config.useServerProxy, base.useServerProxy),
		gcsBucket: str(config.gcsBucket, ""),
		snapshotPrefix: str(config.snapshotPrefix, base.snapshotPrefix),
		allowEgress: bool(config.allowEgress, base.allowEgress),
		target: str(config.target, base.target),
		snapshot: str(config.snapshot, ""),
		autoStopInterval: num(config.autoStopInterval, base.autoStopInterval),
	};
};

const splitList = (value: string): string[] =>
	value
		.split(",")
		.map((entry) => entry.trim())
		.filter(Boolean);

const buildConfig = (form: SandboxFormState): Record<string, unknown> => {
	const base = {
		defaultPackages: splitList(form.defaultPackages),
		timeout: Number(form.timeout) || 1800,
	};
	if (form.provider === "opensandbox") {
		return {
			...base,
			defaultImage: form.defaultImage.trim() || "python:3.12-slim",
			volumeMounts: splitList(form.volumeMounts),
			useServerProxy: form.useServerProxy,
		};
	}
	if (form.provider === "cloudrun") {
		return {
			...base,
			gcsBucket: form.gcsBucket.trim() || null,
			snapshotPrefix: form.snapshotPrefix.trim() || "sandbox-snapshots/",
			allowEgress: form.allowEgress,
		};
	}
	return {
		...base,
		target: form.target.trim() || "us",
		snapshot: form.snapshot.trim() || null,
		autoStopInterval: Number(form.autoStopInterval) || 15,
	};
};

const extractDetail = (error: unknown): string => {
	if (
		error instanceof Object &&
		"response" in error &&
		error.response instanceof Object &&
		"data" in error.response &&
		error.response.data instanceof Object &&
		"detail" in error.response.data &&
		typeof error.response.data.detail === "string"
	) {
		return error.response.data.detail;
	}
	return "Something went wrong. Please try again.";
};

const inputClass =
	"w-full rounded-lg border border-input bg-card px-3 py-[9px] text-[13.5px] font-medium text-foreground outline-none transition-[border-color,box-shadow] placeholder:text-meta dark:placeholder:text-panel-dim focus:border-petrol focus:shadow-[0_0_0_3px_rgba(22,96,110,0.10)]";

function Field({
	id,
	label,
	children,
}: {
	id: string;
	label: string;
	children: React.ReactNode;
}) {
	return (
		<div className="flex flex-col gap-[7px]">
			<label
				htmlFor={id}
				className="text-[13px] font-semibold text-ink dark:text-panel-button"
			>
				{label}
			</label>
			{children}
		</div>
	);
}

function SwitchRow({
	label,
	checked,
	onCheckedChange,
}: {
	label: string;
	checked: boolean;
	onCheckedChange: (checked: boolean) => void;
}) {
	return (
		<div className="flex items-center justify-between">
			<span className="text-[13px] font-semibold text-ink dark:text-panel-button">
				{label}
			</span>
			<Switch
				checked={checked}
				onCheckedChange={onCheckedChange}
				className="cursor-pointer data-[state=checked]:bg-petrol"
			/>
		</div>
	);
}

interface SandboxDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	/** null = create mode; a sandbox = edit mode (provider locked). */
	sandbox: Sandbox | null;
	onSaved: (sandbox: Sandbox) => void;
}

export default function SandboxDialog({
	open,
	onOpenChange,
	sandbox,
	onSaved,
}: SandboxDialogProps) {
	const [form, setForm] = useState<SandboxFormState>(defaultForm());
	const [secretHint, setSecretHint] = useState<SandboxSecretHint | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [isSaving, setIsSaving] = useState(false);
	const isEdit = sandbox !== null;
	const spec = SANDBOX_PROVIDER_SPECS[form.provider];

	const setField = <K extends keyof SandboxFormState>(
		key: K,
		value: SandboxFormState[K],
	) => {
		setForm((prev) => ({ ...prev, [key]: value }));
	};

	useEffect(() => {
		if (!open) return;
		setForm(sandbox ? fromSandbox(sandbox) : defaultForm());
		setError(null);
		setSecretHint(null);
		if (sandbox?.hasSecret) {
			api
				.get(`/sandboxes/${sandbox.id}/secret-hint`)
				.then((response) => {
					setSecretHint(response.data as SandboxSecretHint);
				})
				.catch(() => {
					// Hint is cosmetic — the placeholder falls back to a generic note.
				});
		}
	}, [open, sandbox]);

	const handleProviderChange = (provider: SandboxProviderType) => {
		setForm((prev) => {
			const previousDefault = SANDBOX_PROVIDER_SPECS[prev.provider].defaultUrl;
			const nextDefault = SANDBOX_PROVIDER_SPECS[provider].defaultUrl;
			const url =
				prev.url === "" || prev.url === previousDefault
					? (nextDefault ?? "")
					: prev.url;
			return { ...prev, provider, url };
		});
	};

	const handleSubmit = async (event: React.FormEvent) => {
		event.preventDefault();
		setIsSaving(true);
		setError(null);
		try {
			const payload = {
				name: form.name.trim(),
				description: form.description.trim() || null,
				url: form.url.trim(),
				config: buildConfig(form),
				...(form.secret ? { secret: form.secret } : {}),
			};
			const response = isEdit
				? await api.patch(`/sandboxes/${sandbox.id}`, payload)
				: await api.post("/sandboxes", { ...payload, provider: form.provider });
			onSaved(response.data as Sandbox);
			onOpenChange(false);
		} catch (err: unknown) {
			setError(extractDetail(err));
		} finally {
			setIsSaving(false);
		}
	};

	const secretPlaceholder = isEdit
		? sandbox.hasSecret
			? secretHint?.last4
				? `••••••${secretHint.last4} — leave blank to keep`
				: "Saved — leave blank to keep"
			: spec.secretRequired
				? "Required"
				: "Optional"
		: spec.secretRequired
			? "Required"
			: "Optional";

	const canSubmit =
		form.name.trim() !== "" &&
		form.url.trim() !== "" &&
		(!spec.secretRequired ||
			form.secret.trim() !== "" ||
			(isEdit && sandbox.hasSecret));

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="sm:max-w-[560px]">
				<DialogHeader>
					<DialogTitle>{isEdit ? "Edit sandbox" : "Add sandbox"}</DialogTitle>
					<DialogDescription>
						{isEdit
							? "Update where this sandbox runs. Agents pick the change up on their next run."
							: "Register an execution backend agents can run code in."}
					</DialogDescription>
				</DialogHeader>
				<form
					onSubmit={(e) => {
						void handleSubmit(e);
					}}
					className="flex flex-col gap-4"
				>
					{error && (
						<div className="rounded-[10px] bg-[#FBEFED] px-3.5 py-2.5 text-[13px] font-medium text-[#B04A3A] dark:bg-[#B04A3A]/10">
							{error}
						</div>
					)}

					<div className="max-h-[60vh] overflow-y-auto pr-1 [scrollbar-width:thin]">
						<div className="flex flex-col gap-4">
							<div className="flex flex-col gap-[7px]">
								<span className="text-[13px] font-semibold text-ink dark:text-panel-button">
									Provider
								</span>
								<div className="grid grid-cols-3 gap-1.5">
									{PROVIDER_ORDER.map((provider) => (
										<button
											key={provider}
											type="button"
											disabled={isEdit}
											onClick={() => {
												handleProviderChange(provider);
											}}
											className={`flex cursor-pointer items-center justify-center gap-2 rounded-lg border px-3 py-[9px] text-[13px] font-semibold transition-colors disabled:cursor-default disabled:opacity-50 ${
												form.provider === provider
													? "border-petrol bg-petrol/5 text-petrol dark:text-panel-terminal"
													: "border-input text-subtle hover:border-petrol/40 hover:text-foreground dark:text-panel-body"
											}`}
										>
											<Image
												unoptimized
												width={14}
												height={14}
												src={SANDBOX_PROVIDER_ICONS[provider]}
												alt=""
												className="rounded-[2px] object-contain"
											/>
											{SANDBOX_PROVIDER_SPECS[provider].label}
										</button>
									))}
								</div>
							</div>

							<Field id="sandbox-name" label="Name">
								<input
									id="sandbox-name"
									type="text"
									value={form.name}
									placeholder="e.g. Data lab"
									required
									onChange={(e) => {
										setField("name", e.target.value);
									}}
									className={inputClass}
								/>
							</Field>

							<Field id="sandbox-description" label="Description (optional)">
								<input
									id="sandbox-description"
									type="text"
									value={form.description}
									placeholder="What this sandbox is for"
									onChange={(e) => {
										setField("description", e.target.value);
									}}
									className={inputClass}
								/>
							</Field>

							<Field id="sandbox-url" label={spec.urlLabel}>
								<input
									id="sandbox-url"
									type="text"
									value={form.url}
									placeholder={spec.urlPlaceholder}
									required
									onChange={(e) => {
										setField("url", e.target.value);
									}}
									className={inputClass}
								/>
							</Field>

							<Field id="sandbox-secret" label={spec.secretLabel}>
								<input
									id="sandbox-secret"
									type="password"
									value={form.secret}
									placeholder={secretPlaceholder}
									autoComplete="new-password"
									onChange={(e) => {
										setField("secret", e.target.value);
									}}
									className={inputClass}
								/>
							</Field>

							<div className="grid grid-cols-2 gap-3">
								<Field id="sandbox-packages" label="Default packages">
									<input
										id="sandbox-packages"
										type="text"
										value={form.defaultPackages}
										placeholder="pandas, numpy"
										onChange={(e) => {
											setField("defaultPackages", e.target.value);
										}}
										className={inputClass}
									/>
								</Field>
								<Field id="sandbox-timeout" label="Timeout (seconds)">
									<input
										id="sandbox-timeout"
										type="number"
										min={60}
										value={form.timeout}
										onChange={(e) => {
											setField("timeout", e.target.value);
										}}
										className={inputClass}
									/>
								</Field>
							</div>

							{form.provider === "opensandbox" && (
								<>
									<Field id="sandbox-image" label="Default image">
										<input
											id="sandbox-image"
											type="text"
											value={form.defaultImage}
											placeholder="python:3.12-slim"
											onChange={(e) => {
												setField("defaultImage", e.target.value);
											}}
											className={inputClass}
										/>
									</Field>
									<Field id="sandbox-volumes" label="Volume mounts (optional)">
										<input
											id="sandbox-volumes"
											type="text"
											value={form.volumeMounts}
											placeholder="volume:/mnt/data, other:/mnt/other"
											onChange={(e) => {
												setField("volumeMounts", e.target.value);
											}}
											className={inputClass}
										/>
									</Field>
									<SwitchRow
										label="Use server proxy"
										checked={form.useServerProxy}
										onCheckedChange={(checked) => {
											setField("useServerProxy", checked);
										}}
									/>
								</>
							)}

							{form.provider === "cloudrun" && (
								<>
									<div className="grid grid-cols-2 gap-3">
										<Field id="sandbox-bucket" label="GCS bucket (optional)">
											<input
												id="sandbox-bucket"
												type="text"
												value={form.gcsBucket}
												placeholder="my-snapshots-bucket"
												onChange={(e) => {
													setField("gcsBucket", e.target.value);
												}}
												className={inputClass}
											/>
										</Field>
										<Field id="sandbox-prefix" label="Snapshot prefix">
											<input
												id="sandbox-prefix"
												type="text"
												value={form.snapshotPrefix}
												onChange={(e) => {
													setField("snapshotPrefix", e.target.value);
												}}
												className={inputClass}
											/>
										</Field>
									</div>
									<SwitchRow
										label="Allow network egress"
										checked={form.allowEgress}
										onCheckedChange={(checked) => {
											setField("allowEgress", checked);
										}}
									/>
								</>
							)}

							{form.provider === "daytona" && (
								<div className="grid grid-cols-3 gap-3">
									<Field id="sandbox-target" label="Region">
										<input
											id="sandbox-target"
											type="text"
											value={form.target}
											placeholder="us"
											onChange={(e) => {
												setField("target", e.target.value);
											}}
											className={inputClass}
										/>
									</Field>
									<Field id="sandbox-snapshot" label="Snapshot (optional)">
										<input
											id="sandbox-snapshot"
											type="text"
											value={form.snapshot}
											onChange={(e) => {
												setField("snapshot", e.target.value);
											}}
											className={inputClass}
										/>
									</Field>
									<Field id="sandbox-autostop" label="Auto-stop (min)">
										<input
											id="sandbox-autostop"
											type="number"
											min={0}
											value={form.autoStopInterval}
											onChange={(e) => {
												setField("autoStopInterval", e.target.value);
											}}
											className={inputClass}
										/>
									</Field>
								</div>
							)}
						</div>
					</div>

					<DialogFooter>
						<DialogButton
							variant="outline"
							onClick={() => {
								onOpenChange(false);
							}}
						>
							Cancel
						</DialogButton>
						<DialogButton type="submit" disabled={isSaving || !canSubmit}>
							{isSaving
								? "Saving…"
								: isEdit
									? "Save changes"
									: "Add sandbox"}
						</DialogButton>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
