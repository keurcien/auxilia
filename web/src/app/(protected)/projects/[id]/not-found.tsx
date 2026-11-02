import Link from "next/link";
import { FolderX } from "lucide-react";

export default function ProjectNotFound() {
	return (
		<div className="flex h-full flex-1 items-center justify-center bg-background px-6">
			<div className="max-w-sm text-center">
				<span className="mx-auto flex size-12 items-center justify-center rounded-[12px] bg-sidebar text-meta">
					<FolderX className="size-5" />
				</span>
				<h1 className="mt-4 font-display text-[20px] font-bold text-foreground">
					Project unavailable
				</h1>
				<p className="mt-2 text-[12.5px] leading-5 text-meta">
					This project was removed, belongs to another workspace, or is no
					longer shared with you.
				</p>
				<Link
					href="/"
					className="mt-5 inline-flex items-center whitespace-nowrap rounded-[7px] bg-petrol px-4 py-2 text-[12.5px] font-semibold text-white"
				>
					Return to workspace
				</Link>
			</div>
		</div>
	);
}
