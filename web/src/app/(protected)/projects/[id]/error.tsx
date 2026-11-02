"use client";

import Link from "next/link";
import { CircleAlert, RotateCw } from "lucide-react";

export default function ProjectError({
	reset,
}: {
	error: Error & { digest?: string };
	reset: () => void;
}) {
	return (
		<div className="flex h-full flex-1 items-center justify-center bg-background px-6">
			<div className="max-w-sm text-center">
				<span className="mx-auto flex size-12 items-center justify-center rounded-[12px] bg-destructive/10 text-destructive">
					<CircleAlert className="size-5" />
				</span>
				<h1 className="mt-4 font-display text-[20px] font-bold text-foreground">
					Project could not be loaded
				</h1>
				<p className="mt-2 text-[12.5px] leading-5 text-meta">
					Try loading it again. If the problem continues, return to the
					workspace.
				</p>
				<div className="mt-5 flex items-center justify-center gap-2">
					<Link
						href="/"
						className="inline-flex items-center whitespace-nowrap rounded-[7px] border border-input bg-card px-4 py-2 text-[12.5px] font-semibold text-foreground"
					>
						Return to workspace
					</Link>
					<button
						type="button"
						onClick={reset}
						className="inline-flex cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-[7px] bg-petrol px-4 py-2 text-[12.5px] font-semibold text-white"
					>
						<RotateCw className="size-3.5" />
						Try again
					</button>
				</div>
			</div>
		</div>
	);
}
