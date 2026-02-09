"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import Image from "next/image";
import {
	Dialog,
	DialogContent,
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

				// Poll is-connected-v2 until connected
				pollRef.current = setInterval(async () => {
					try {
						const res = await api.get(
							`/mcp-servers/${server.id}/is-connected-v2`,
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
			<DialogContent className="sm:max-w-[480px]">
				<DialogHeader>
					<DialogTitle className="text-xl">Authentication Required</DialogTitle>
					<DialogDescription>
						To use this agent, you need to authenticate with{" "}
						{disconnectedServers.length === 1
							? disconnectedServers[0].name
							: `${disconnectedServers.length} services`}
						.
					</DialogDescription>
				</DialogHeader>

				<div className="space-y-2 mt-2">
					{disconnectedServers.map((server) => {
						const isConnected = connectedIds.has(server.id);
						const isCurrent = currentServer?.id === server.id && !isConnected;

						return (
							<div
								key={server.id}
								className={`flex items-center gap-3 rounded-xl p-3 transition-colors ${
									isCurrent
										? "bg-blue-50 border border-blue-200"
										: isConnected
											? "bg-green-50 border border-green-200"
											: "bg-gray-50 border border-gray-100"
								}`}
							>
								<div className="w-8 h-8 rounded-md flex items-center justify-center overflow-hidden relative shrink-0">
									<Image
										width={32}
										height={32}
										src={
											server.iconUrl ??
											"https://storage.googleapis.com/choose-assets/mcp.png"
										}
										alt={server.name}
										className="object-cover"
									/>
								</div>
								<span className="text-sm font-medium flex-1">
									{server.name}
								</span>
								{isConnected ? (
									<CheckCircle2Icon className="w-5 h-5 text-green-600" />
								) : isCurrent ? (
									<span className="text-xs font-medium text-blue-600">
										Current
									</span>
								) : null}
							</div>
						);
					})}
				</div>

				{currentServer && (
					<button
						onClick={() => handleConnect(currentServer)}
						disabled={connectingId !== null}
						className="w-full mt-2 px-5 py-3 bg-black text-white text-sm font-medium rounded-xl hover:bg-gray-800 transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
					>
						{connectingId === currentServer.id ? (
							<>
								<LoaderIcon className="w-4 h-4 animate-spin" />
								Waiting for authentication...
							</>
						) : (
							<>Authenticate with {currentServer.name}</>
						)}
					</button>
				)}
			</DialogContent>
		</Dialog>
	);
}
