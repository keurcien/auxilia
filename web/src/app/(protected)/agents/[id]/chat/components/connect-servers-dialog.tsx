"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import {
	Dialog,
	DialogButton,
	DialogContent,
	DialogFooter,
	DialogHeader,
	DialogTitle,
	DialogDescription,
} from "@/components/ui/dialog";
import * as mcpServersApi from "@/lib/api/resources/mcp-servers";
import { MCPServer } from "@/types/mcp-servers";
import { CheckCircle2Icon, LoaderIcon } from "lucide-react";
import { ServerIconTile } from "@/app/(protected)/mcp-servers/components/server-icon-tile";

interface ConnectServersDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	disconnectedServers: MCPServer[];
	onAllConnected: () => void;
}

export function ConnectServersDialog({
	open,
	onOpenChange,
	disconnectedServers,
	onAllConnected,
}: ConnectServersDialogProps) {
	const [connectedIds, setConnectedIds] = useState<Set<string>>(new Set());
	const [connectingId, setConnectingId] = useState<string | null>(null);
	const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
	const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

	const remainingServers = disconnectedServers.filter(
		(s) => !connectedIds.has(s.id),
	);

	// When all servers are connected, notify parent and close
	useEffect(() => {
		if (
			open &&
			disconnectedServers.length > 0 &&
			remainingServers.length === 0
		) {
			onAllConnected();
			onOpenChange(false);
		}
	}, [
		remainingServers.length,
		disconnectedServers.length,
		open,
		onAllConnected,
		onOpenChange,
	]);

	// Cleanup on unmount or close
	useEffect(() => {
		if (!open) {
			if (pollRef.current) clearInterval(pollRef.current);
			if (timeoutRef.current) clearTimeout(timeoutRef.current);
			// Resetting on close is intentional and safe here.
			// eslint-disable-next-line react-hooks/set-state-in-effect
			setConnectingId(null);
		}
	}, [open]);

	const handleConnect = useCallback(async (server: MCPServer) => {
		setConnectingId(server.id);

		try {
			// list-tools answers with the tools, or with the URL the user must
			// open first — both are 200s (a discriminated union on `status`).
			const result = await mcpServersApi.listMcpServerTools(server.id);

			if (result.status === "ok") {
				setConnectedIds((prev) => new Set(prev).add(server.id));
				setConnectingId(null);
			} else {
				const popup = window.open(
					result.authUrl,
					"_blank",
					"width=600,height=700",
				);
				if (!popup) {
					// Popup blocked: tell the user instead of silently timing out.
					console.error("Popup blocked for", server.name);
					setConnectingId(null);
					return;
				}

				// Poll is-connected until connected
				const poll = async () => {
					try {
						if (await mcpServersApi.isMcpServerConnected(server.id)) {
							if (pollRef.current) clearInterval(pollRef.current);
							if (timeoutRef.current) clearTimeout(timeoutRef.current);

							setConnectedIds((prev) => new Set(prev).add(server.id));
							setConnectingId(null);

							if (popup && !popup.closed) {
								popup.close();
							}
						}
					} catch {
						// continue polling
					}
				};
				pollRef.current = setInterval(() => {
					void poll();
				}, 2000);

				// Timeout after 60s
				timeoutRef.current = setTimeout(() => {
					if (pollRef.current) clearInterval(pollRef.current);
					setConnectingId(null);
				}, 60000);
			}
		} catch (error: unknown) {
			// Only a real failure lands here now — needing authorization is a
			// 200 with `status: "auth_required"`, handled above.
			console.error("Failed to connect:", error);
			setConnectingId(null);
		}
	}, []);

	const currentServer =
		remainingServers.length > 0 ? remainingServers[0] : null;

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent>
				<DialogHeader>
					<DialogTitle>Connect optional tools</DialogTitle>
					<DialogDescription>
						This agent can run without{" "}
						{disconnectedServers.length === 1
							? disconnectedServers[0].name
							: `${disconnectedServers.length} services`}
						. Connect {disconnectedServers.length === 1 ? "it" : "them"} only
						if you want the related tools to be available.
					</DialogDescription>
				</DialogHeader>

				<div className="flex flex-col gap-2">
					{disconnectedServers.map((server) => {
						const isConnected = connectedIds.has(server.id);
						const isCurrent = currentServer?.id === server.id && !isConnected;

						return (
							<div
								key={server.id}
								className={`flex items-center gap-3 rounded-[10px] border p-3 transition-colors ${
									isCurrent
										? "border-sparkline bg-[#F2F8F8] dark:border-petrol/40 dark:bg-petrol/10"
										: isConnected
											? "border-success-bg bg-success-bg/50 dark:border-success/30 dark:bg-success/10"
											: "border-hairline bg-sidebar dark:bg-white/5"
								}`}
							>
								<ServerIconTile
									iconUrl={server.iconUrl}
									serverId={server.id}
									imageRevision={server.imageRevision}
									name={server.name}
									size={32}
								/>
								<span className="flex-1 text-[13.5px] font-semibold text-ink dark:text-panel-button">
									{server.name}
								</span>
								{isConnected ? (
									<CheckCircle2Icon className="size-5 text-success" />
								) : isCurrent ? (
									<span className="text-[10.5px] font-semibold text-petrol dark:text-panel-terminal">
										Current
									</span>
								) : null}
							</div>
						);
					})}
				</div>

				{currentServer && (
					<DialogFooter>
						<DialogButton
							onClick={() => { void handleConnect(currentServer); }}
							disabled={connectingId !== null}
						>
							{connectingId === currentServer.id ? (
								<>
									<LoaderIcon className="size-4 animate-spin" />
									Waiting for authentication…
								</>
							) : (
								<>Connect {currentServer.name}</>
							)}
						</DialogButton>
					</DialogFooter>
				)}
			</DialogContent>
		</Dialog>
	);
}
