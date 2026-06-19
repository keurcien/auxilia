import { useMemo, useSyncExternalStore } from "react";
import type { McpUiHostContext, McpUiStyles } from "@modelcontextprotocol/ext-apps";

/**
 * WHY: MCP Apps receive theme info from the host via hostContext.
 * Without this, sandboxed MCP app iframes fall back to their own
 * hardcoded defaults (usually light theme), ignoring the host's theme.
 */

type AuxiliaToken = string;
type McpVariable = keyof McpUiStyles;

const TOKEN_MAP: [McpVariable, AuxiliaToken][] = [
	["--color-background-primary", "--background"],
	["--color-background-secondary", "--card"],
	["--color-background-tertiary", "--accent"],
	["--color-background-inverse", "--primary"],
	["--color-background-ghost", "--background"],
	["--color-background-info", "--accent"],
	["--color-background-danger", "--destructive"],
	["--color-background-success", "--accent"],
	["--color-background-warning", "--accent"],
	["--color-background-disabled", "--muted"],

	["--color-text-primary", "--foreground"],
	["--color-text-secondary", "--muted-foreground"],
	["--color-text-tertiary", "--muted-foreground"],
	["--color-text-inverse", "--primary-foreground"],
	["--color-text-ghost", "--muted-foreground"],
	["--color-text-info", "--foreground"],
	["--color-text-danger", "--destructive"],
	["--color-text-success", "--foreground"],
	["--color-text-warning", "--foreground"],
	["--color-text-disabled", "--muted-foreground"],

	["--color-border-primary", "--border"],
	["--color-border-secondary", "--border"],
	["--color-border-tertiary", "--border"],
	["--color-border-inverse", "--primary"],
	["--color-border-ghost", "--border"],
	["--color-border-info", "--border"],
	["--color-border-danger", "--destructive"],
	["--color-border-success", "--border"],
	["--color-border-warning", "--border"],
	["--color-border-disabled", "--muted"],

	["--color-ring-primary", "--ring"],
	["--color-ring-secondary", "--ring"],
	["--color-ring-inverse", "--primary-foreground"],
	["--color-ring-info", "--ring"],
	["--color-ring-danger", "--destructive"],
	["--color-ring-success", "--ring"],
	["--color-ring-warning", "--ring"],

	["--border-radius-sm", "--radius"],
	["--border-radius-md", "--radius"],
	["--border-radius-lg", "--radius"],
	["--border-radius-xl", "--radius"],
];

function getTheme(): "light" | "dark" {
	if (typeof document === "undefined") return "light";
	return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

function subscribeToTheme(callback: () => void): () => void {
	const observer = new MutationObserver(callback);
	observer.observe(document.documentElement, {
		attributes: true,
		attributeFilter: ["class"],
	});
	return () => observer.disconnect();
}

// MCP apps embed parsers that can't read CSS Color 4 (`oklch()` / `lab()`), and
// our Tailwind v4 theme tokens are authored in `oklch()`. `getComputedStyle`
// doesn't downconvert (Chrome re-serializes to `lab()`), so round-trip each color
// through a canvas 2D context, which parses CSS Color 4 and serializes back to a
// legacy `rgb()`/`#hex` every parser understands.
let _colorCanvasCtx: CanvasRenderingContext2D | null | undefined;

function normalizeColor(value: string): string {
	if (typeof document === "undefined") return value;
	if (_colorCanvasCtx === undefined) {
		_colorCanvasCtx = document.createElement("canvas").getContext("2d");
	}
	if (!_colorCanvasCtx) return value;
	// Assigning an unparseable value leaves fillStyle unchanged; seed a sentinel
	// so we can detect that and fall back to the original string.
	const sentinel = "#000001";
	_colorCanvasCtx.fillStyle = sentinel;
	_colorCanvasCtx.fillStyle = value;
	const normalized = _colorCanvasCtx.fillStyle;
	return normalized === sentinel && value !== sentinel ? value : normalized;
}

function resolveStyleVariables(): Partial<McpUiStyles> {
	if (typeof document === "undefined") return {};

	const computed = getComputedStyle(document.documentElement);
	const variables: Partial<McpUiStyles> = {};

	for (const [mcpKey, auxiliaToken] of TOKEN_MAP) {
		const value = computed.getPropertyValue(auxiliaToken).trim();
		if (value) {
			variables[mcpKey] = mcpKey.startsWith("--color-")
				? normalizeColor(value)
				: value;
		}
	}

	return variables;
}

export function useMcpHostContext(): McpUiHostContext {
	const theme = useSyncExternalStore(
		subscribeToTheme,
		getTheme,
		() => "light" as const,
	);

	// Memoize by theme — style variables only change with the theme class flip.
	// Without this, every parent re-render produces a new hostContext object,
	// which makes AppRenderer re-sync to the sandboxed iframe on every tick and
	// floods the console with "Ignoring message from unknown source" warnings.
	return useMemo<McpUiHostContext>(
		() => ({
			theme,
			styles: {
				variables: resolveStyleVariables() as McpUiStyles,
			},
			platform: "web",
			deviceCapabilities: { touch: false, hover: true },
		}),
		[theme],
	);
}
