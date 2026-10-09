"use client";

import { useEffect, useId, useState } from "react";
import { Copy } from "lucide-react";
import { toast } from "sonner";
import * as mcpServersApi from "@/lib/api/resources/mcp-servers";

export function OAuthCallbackUrl({ showLabel = true }: { showLabel?: boolean }) {
	const inputId = useId();
	const [callbackUrl, setCallbackUrl] = useState("");

	useEffect(() => {
		const controller = new AbortController();

		void mcpServersApi
			.getOAuthCallbackInfo({ signal: controller.signal })
			.then((result) => {
				setCallbackUrl(result.callbackUrl);
			})
			.catch(() => {
				if (!controller.signal.aborted) setCallbackUrl("");
			});

		return () => {
			controller.abort();
		};
	}, []);

	const handleCopy = () => {
		if (!callbackUrl) return;
		void navigator.clipboard
			.writeText(callbackUrl)
			.then(() => {
				toast.success("Callback URL copied");
			})
			.catch(() => {
				toast.error("Could not copy the callback URL");
			});
	};

	return (
		<div className="flex flex-col gap-[7px]">
			{showLabel && (
				<label
					htmlFor={inputId}
					className="text-[11px] font-semibold uppercase tracking-[0.07em] text-meta dark:text-panel-dim"
				>
					Callback URL
				</label>
			)}
			<div className="relative">
				<input
					id={inputId}
					readOnly
					aria-busy={!callbackUrl}
					value={callbackUrl}
					placeholder="Loading callback URL…"
					className="h-10 w-full rounded-lg border border-border bg-background px-3 pr-10 font-mono text-[12px] text-foreground outline-none dark:bg-white/5"
				/>
				<button
					type="button"
					disabled={!callbackUrl}
					onClick={handleCopy}
					aria-label="Copy callback URL"
					title="Copy callback URL"
					className="absolute right-2 top-1/2 flex size-7 -translate-y-1/2 cursor-pointer items-center justify-center rounded-md text-meta transition-colors hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
				>
					<Copy className="size-3.5" />
				</button>
			</div>
			<p className="text-[12px] leading-[1.5] text-meta dark:text-panel-dim">
				Register this exact URL as an authorized redirect URI in the provider&apos;s
				OAuth application.
			</p>
		</div>
	);
}
