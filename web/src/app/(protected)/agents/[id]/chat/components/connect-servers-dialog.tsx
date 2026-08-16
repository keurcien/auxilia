"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import Image from "next/image";
import {
	Dialog,
	DialogContent,
	DialogFooter,
	DialogHeader,
	DialogTitle,
	DialogDescription,
} from "@/components/ui/dialog";
import { api } from "@/lib/api/client";
import { MCPServer } from "@/types/mcp-servers";
import { CheckCircle2Icon, LoaderIcon } from "lucide-react";

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
			// Trigger the list-tools call which will return 401 with auth_url for OAuth servers
			await api.get(`/mcp-servers/${server.id}/list-tools`);
			// If it succeeds without error, server is already connected
			setConnectedIds((prev) => new Set(prev).add(server.id));
			setConnectingId(null);
		} catch (error: unknown) {
			if (
				error &&
				typeof error === "object" &&
				"response" in error &&
				error.response &&
				typeof error.response === "object" &&
				"status" in error.response &&
				error.response.status === 401 &&
				"data" in error.response &&
				error.response.data &&
				typeof error.response.data === "object" &&
				"auth_url" in error.response.data
			) {
				const authUrl = error.response.data.auth_url as string;
				const popup = window.open(authUrl, "_blank", "width=600,height=700");
				if (!popup) {
					// Popup blocked: tell the user instead of silently timing out.
					console.error("Popup blocked for", server.name);
					setConnectingId(null);
					return;
				}

				// Poll is-connected until connected
				const poll = async () => {
					try {
						const res = await api.get(
							`/mcp-servers/${server.id}/is-connected`,
						);
						if (res.data.connected) {
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
			} else {
				console.error("Failed to connect:", error);
				setConnectingId(null);
			}
		}
	}, []);

	const currentServer =
		remainingServers.length > 0 ? remainingServers[0] : null;

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent>
				<DialogHeader>
					<DialogTitle>Authentication required</DialogTitle>
					<DialogDescription>
						To use this agent, you need to authenticate with{" "}
						{disconnectedServers.length === 1
							? disconnectedServers[0].name
							: `${disconnectedServers.length} services`}
						.
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
								<div className="relative flex size-8 shrink-0 items-center justify-center overflow-hidden rounded-md">
									<Image
										unoptimized
										width={32}
										height={32}
										src={
											server.iconUrl ??
											"https://pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev/assets/icons/mcp.png"
										}
										alt={server.name}
										className="object-cover"
									/>
								</div>
								<span className="flex-1 text-[13.5px] font-semibold text-ink dark:text-panel-button">
									{server.name}
								</span>
								{isConnected ? (
									<CheckCircle2Icon className="size-5 text-success" />
								) : isCurrent ? (
									<span className="font-mono text-[10.5px] font-semibold tracking-[0.05em] text-petrol dark:text-panel-terminal">
										CURRENT
									</span>
								) : null}
							</div>
						);
					})}
				</div>

				{currentServer && (
					<DialogFooter>
						<button
							onClick={() => { void handleConnect(currentServer); }}
							disabled={connectingId !== null}
							className="flex cursor-pointer items-center justify-center gap-2 rounded-[7px] bg-petrol px-[18px] py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
						>
							{connectingId === currentServer.id ? (
								<>
									<LoaderIcon className="size-4 animate-spin" />
									Waiting for authentication…
								</>
							) : (
								<>Authenticate with {currentServer.name}</>
							)}
						</button>
					</DialogFooter>
				)}
			</DialogContent>
		</Dialog>
	);
}
