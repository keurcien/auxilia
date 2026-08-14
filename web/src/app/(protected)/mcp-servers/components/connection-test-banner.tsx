import { CircleAlert, CircleCheck, Loader2 } from "lucide-react";
import { ConnectionTestStatus } from "../lib/use-connection-test";

/** Inline result strip for a connection test (form + detail pages). */
export function ConnectionTestBanner({
	status,
	message,
}: {
	status: ConnectionTestStatus;
	message: string | null;
}) {
	if (status === "idle" || message === null) return null;

	const className =
		status === "success"
			? "bg-success-bg text-success dark:bg-emerald-950 dark:text-emerald-300"
			: status === "error"
				? "bg-destructive/10 text-destructive"
				: "bg-hover text-subtle dark:bg-white/5 dark:text-panel-body";

	return (
		<div
			className={`flex items-center gap-2.5 rounded-[10px] px-4 py-3 text-[13px] font-medium ${className}`}
		>
			{status === "success" ? (
				<CircleCheck className="size-4 shrink-0" />
			) : status === "error" ? (
				<CircleAlert className="size-4 shrink-0" />
			) : (
				<Loader2 className="size-4 shrink-0 animate-spin" />
			)}
			<span>{message}</span>
		</div>
	);
}
