"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import { BookOpen, ExternalLink, Github } from "lucide-react";

import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { appearanceLogoUrl } from "@/lib/api/resources/appearance";
import { getBackendVersion } from "@/lib/api/resources/system";
import { useAppearanceStore } from "@/stores/appearance-store";
import packageJson from "../../../../package.json";

const GITHUB_URL = "https://github.com/keurcien/auxilia";
const DOCUMENTATION_URL = "https://auxilia-docs.vercel.app/";

interface AboutDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
}

export function AboutDialog({ open, onOpenChange }: AboutDialogProps) {
	const [backendVersion, setBackendVersion] = useState<string | null>();
	const appearance = useAppearanceStore((state) => state.appearance);

	useEffect(() => {
		if (!open || backendVersion !== undefined) return;

		const controller = new AbortController();
		getBackendVersion(controller.signal)
			.then((version) => {
				setBackendVersion(version);
			})
			.catch(() => {
				if (!controller.signal.aborted) setBackendVersion(null);
			});

		return () => {
			controller.abort();
		};
	}, [open, backendVersion]);

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="overflow-hidden p-0 sm:max-w-[440px]">
				<div className="border-b border-hairline px-7 pb-6 pt-8 dark:border-white/10">
					<div className="mb-4 flex justify-center">
						{appearance.logoRevision ? (
							<Image
								src={appearanceLogoUrl(appearance.logoRevision)}
								alt={appearance.appName}
								width={34}
								height={34}
								className="size-[34px]"
							/>
						) : (
							<>
								<Image
									src="/logo.svg"
									alt={appearance.appName}
									width={34}
									height={34}
									className="size-[34px] dark:hidden"
								/>
								<Image
									src="/logo-dark.svg"
									alt={appearance.appName}
									width={34}
									height={34}
									className="hidden size-[34px] dark:block"
								/>
							</>
						)}
					</div>
					<DialogHeader className="items-center text-center">
						<DialogTitle className="text-[22px] tracking-[-0.03em]">
							{appearance.appName}
						</DialogTitle>
						<DialogDescription className="max-w-[340px] text-[13.5px] leading-relaxed">
							An open-source web client for building and running
							MCP-powered AI assistants.
						</DialogDescription>
						<div className="flex gap-2 pt-2">
							<span className="rounded-[5px] border border-petrol/15 bg-petrol/8 px-2.5 py-1 font-mono text-[10px] font-semibold text-petrol dark:border-white/10 dark:bg-white/8 dark:text-panel-dim">
								Frontend v{packageJson.version}
							</span>
							<span className="rounded-[5px] border border-petrol/15 bg-petrol/8 px-2.5 py-1 font-mono text-[10px] font-semibold text-petrol dark:border-white/10 dark:bg-white/8 dark:text-panel-dim">
								Backend{" "}
								{backendVersion === undefined
									? "…"
									: backendVersion === null
										? "unavailable"
										: `v${backendVersion}`}
							</span>
						</div>
					</DialogHeader>
				</div>

				<div className="grid gap-2 px-7 pb-7 pt-5">
					<a
						href={GITHUB_URL}
						target="_blank"
						rel="noreferrer"
						className="group flex items-center gap-3 rounded-[9px] border border-hairline px-3.5 py-3 text-[13px] font-semibold text-ink transition-colors hover:border-border-hover hover:bg-hover dark:border-white/10 dark:text-panel-button dark:hover:border-white/20 dark:hover:bg-white/5"
					>
						<Github className="size-[17px] text-label" />
						GitHub
						<ExternalLink className="ml-auto size-3.5 text-meta transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
					</a>
					<a
						href={DOCUMENTATION_URL}
						target="_blank"
						rel="noreferrer"
						className="group flex items-center gap-3 rounded-[9px] border border-hairline px-3.5 py-3 text-[13px] font-semibold text-ink transition-colors hover:border-border-hover hover:bg-hover dark:border-white/10 dark:text-panel-button dark:hover:border-white/20 dark:hover:bg-white/5"
					>
						<BookOpen className="size-[17px] text-label" />
						Documentation
						<ExternalLink className="ml-auto size-3.5 text-meta transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
					</a>
					<p className="mt-3 text-center text-[10.5px] text-meta">
						Licensed under AGPL-3.0-or-later
					</p>
				</div>
			</DialogContent>
		</Dialog>
	);
}
