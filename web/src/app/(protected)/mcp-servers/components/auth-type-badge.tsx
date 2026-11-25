import {
	MCPAuthType,
	MCPCredentialScope,
	usesUserCredentials,
} from "@/types/mcp-servers";
import { cn } from "@/lib/utils";

// Exhaustive switch (not a keyed lookup) so static analysis can verify the
// access — the union type guarantees every case is covered.
function badgeFor(
	authType: MCPAuthType,
	personal: boolean,
): { label: string; className: string } {
	switch (authType) {
		case "oauth2":
			return {
				label: "OAuth 2.0",
				className:
					"bg-[#E7F0FA] text-[#2E6FA8] dark:bg-sky-950 dark:text-sky-300",
			};
		case "api_key":
			return {
				label: personal ? "Personal API key" : "API Key Bearer",
				className: personal
					? "bg-[#E7F0FA] text-[#2E6FA8] dark:bg-sky-950 dark:text-sky-300"
					: "bg-neutral-bg text-subtle dark:bg-white/10 dark:text-panel-body",
			};
		case "service_identity":
			return {
				label: "Service identity",
				className:
					"bg-[#E8F3EE] text-[#2E7054] dark:bg-emerald-950 dark:text-emerald-300",
			};
		case "custom_http":
			return {
				label: personal ? "Personal HTTP" : "Custom HTTP",
				className: personal
					? "bg-[#E7F0FA] text-[#2E6FA8] dark:bg-sky-950 dark:text-sky-300"
					: "bg-[#F3ECE2] text-[#805A2F] dark:bg-amber-950 dark:text-amber-300",
			};
		case "none":
			return {
				label: "Open",
				className:
					"bg-neutral-bg text-subtle dark:bg-white/10 dark:text-panel-body",
			};
	}
}

/** Auth chip. Personal methods (each user brings their own credential) share
 * the OAuth blue; shared ones keep their own tint. */
export function AuthTypeBadge({
	authType,
	credentialScope,
	className,
}: {
	authType: MCPAuthType;
	credentialScope?: MCPCredentialScope;
	className?: string;
}) {
	const badge = badgeFor(
		authType,
		usesUserCredentials({ authType, credentialScope }),
	);
	return (
		<span
			className={cn(
				"inline-flex shrink-0 items-center rounded-[4px] px-2 py-[3px] text-[9.5px] font-semibold ",
				badge.className,
				className,
			)}
		>
			{badge.label}
		</span>
	);
}
