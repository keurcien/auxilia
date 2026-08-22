import type { SandboxProviderType } from "@/types/sandboxes";

export const SANDBOX_PROVIDER_LABELS: Record<SandboxProviderType, string> = {
	opensandbox: "OpenSandbox",
	cloudrun: "Cloud Run",
	daytona: "Daytona",
};

const ICON_BASE = "https://pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev/assets/icons";

export const SANDBOX_PROVIDER_ICONS: Record<SandboxProviderType, string> = {
	opensandbox: `${ICON_BASE}/opensandbox.png`,
	cloudrun: `${ICON_BASE}/cloudrun.png`,
	daytona: `${ICON_BASE}/daytona.png`,
};
