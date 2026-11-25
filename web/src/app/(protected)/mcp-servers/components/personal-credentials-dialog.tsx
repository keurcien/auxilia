"use client";

import { useState } from "react";
import { KeyRound } from "lucide-react";
import {
	Dialog,
	DialogButton,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import * as mcpServersApi from "@/lib/api/resources/mcp-servers";
import { getApiErrorMessage } from "@/lib/api/errors";
import type { MCPAuthType } from "@/types/mcp-servers";

export interface PersonalCredentialsServer {
	id: string;
	name: string;
	authType: MCPAuthType;
	personalHeaderNames?: string[];
}

interface PersonalCredentialsDialogProps {
	server: PersonalCredentialsServer | null;
	onOpenChange: (open: boolean) => void;
	onSaved: (serverId: string) => void;
}

const INPUT_CLASS =
	"w-full rounded-lg border border-input bg-card px-3 py-[9px] font-mono text-[12.5px] text-foreground outline-none transition-[border-color,box-shadow] placeholder:text-meta dark:placeholder:text-panel-dim focus:border-petrol focus:shadow-[0_0_0_3px_rgba(22,96,110,0.10)]";

/**
 * Asks the signed-in user for their own API key or header values on a
 * personal server. The backend verifies them with a handshake before saving.
 */
export function PersonalCredentialsDialog({
	server,
	onOpenChange,
	onSaved,
}: PersonalCredentialsDialogProps) {
	return (
		<Dialog open={server !== null} onOpenChange={onOpenChange}>
			<DialogContent>
				{server && (
					<PersonalCredentialsForm
						key={server.id}
						server={server}
						onCancel={() => {
							onOpenChange(false);
						}}
						onSaved={onSaved}
					/>
				)}
			</DialogContent>
		</Dialog>
	);
}

function PersonalCredentialsForm({
	server,
	onCancel,
	onSaved,
}: {
	server: PersonalCredentialsServer;
	onCancel: () => void;
	onSaved: (serverId: string) => void;
}) {
	const isApiKey = server.authType === "api_key";
	const headerNames = server.personalHeaderNames ?? [];
	const [apiKey, setApiKey] = useState("");
	const [headerValues, setHeaderValues] = useState<string[]>(() =>
		headerNames.map(() => ""),
	);
	const [error, setError] = useState<string | null>(null);
	const [isSaving, setIsSaving] = useState(false);

	const isComplete = isApiKey
		? apiKey.trim().length > 0
		: headerValues.every((value) => value.trim().length > 0);

	const handleSave = async () => {
		if (!isComplete) return;
		setError(null);
		setIsSaving(true);
		try {
			await mcpServersApi.setMyMcpCredentials(
				server.id,
				isApiKey
					? { apiKey: apiKey.trim() }
					: {
							headers: headerNames.map((name, index) => ({
								name,
								value: headerValues[index] ?? "",
							})),
						},
			);
			onSaved(server.id);
		} catch (err: unknown) {
			setError(
				getApiErrorMessage(err, `Could not connect to ${server.name}.`),
			);
		} finally {
			setIsSaving(false);
		}
	};

	return (
		<form
			className="contents"
			onSubmit={(event) => {
				event.preventDefault();
				void handleSave();
			}}
		>
			<DialogHeader>
				<DialogTitle>Connect {server.name}</DialogTitle>
				<DialogDescription>
					{isApiKey
						? "This server uses a personal API key. Enter yours, it is encrypted and only used for your conversations."
						: "This server uses personal HTTP headers. Enter your own values, they are encrypted and only used for your conversations."}
				</DialogDescription>
			</DialogHeader>

			<div className="flex flex-col gap-3">
				{isApiKey ? (
					<label className="flex flex-col gap-[7px]">
						<span className="text-[13px] font-semibold text-foreground">
							API key
						</span>
						<input
							type="password"
							autoFocus
							autoComplete="off"
							placeholder="Enter your Bearer API key"
							value={apiKey}
							onChange={(event) => {
								setApiKey(event.target.value);
								setError(null);
							}}
							className={INPUT_CLASS}
						/>
					</label>
				) : (
					headerNames.map((name, index) => (
						<label key={name} className="flex flex-col gap-[7px]">
							<span className="font-mono text-[12.5px] font-semibold text-foreground">
								{name}
							</span>
							<input
								type="password"
								autoFocus={index === 0}
								autoComplete="off"
								placeholder="Value"
								value={headerValues[index] ?? ""}
								onChange={(event) => {
									const next = event.target.value;
									setHeaderValues((current) =>
										current.map((value, position) =>
											position === index ? next : value,
										),
									);
									setError(null);
								}}
								className={INPUT_CLASS}
							/>
						</label>
					))
				)}
				{error && (
					<p
						className="rounded-[8px] bg-destructive/10 px-3 py-2.5 text-[12px] leading-[1.5] text-destructive"
						aria-live="polite"
					>
						{error}
					</p>
				)}
			</div>

			<DialogFooter className="flex-col-reverse sm:flex-row">
				<DialogButton
					type="button"
					variant="outline"
					className="w-full sm:w-auto"
					onClick={onCancel}
					disabled={isSaving}
				>
					Cancel
				</DialogButton>
				<DialogButton
					type="submit"
					className="w-full sm:w-auto"
					disabled={!isComplete || isSaving}
				>
					<KeyRound className="size-3.5" />
					{isSaving ? "Checking…" : "Connect"}
				</DialogButton>
			</DialogFooter>
		</form>
	);
}
