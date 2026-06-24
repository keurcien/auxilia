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
// our Tailwind v4 theme tokens are authored in `oklch()` (which `getComputedStyle`
// re-serializes to `lab()` in Chrome). Round-trip each color through a canvas 2D
// context to downconvert to 8-bit sRGB. NB: we read the painted *pixel*, not the
// `fillStyle` getter — current Chrome preserves `lab()`/`oklch()` in the getter's
// serialization (whatwg/html#8917), so the getter alone leaves them unchanged.
let _colorCanvasCtx: CanvasRenderingContext2D | null | undefined;

function normalizeColor(value: string): string {
	if (typeof document === "undefined") return value;
	if (_colorCanvasCtx === undefined) {
		// willReadFrequently: this context exists only for getImageData readback
		// (never displayed), so a CPU-backed canvas avoids per-call GPU syncs.
		_colorCanvasCtx = document
			.createElement("canvas")
			.getContext("2d", { willReadFrequently: true });
	}
	const ctx = _colorCanvasCtx;
	if (!ctx) return value;
	// Assigning an unparseable value leaves fillStyle unchanged; seed a sentinel
	// so we can detect that and fall back to the original string.
	const sentinel = "#000001";
	ctx.fillStyle = sentinel;
	ctx.fillStyle = value;
	if (ctx.fillStyle === sentinel && value !== sentinel) return value;
	// Paint one pixel and read it back: getImageData always yields 8-bit sRGB,
	// i.e. a legacy `rgb()`/`rgba()` every MCP-app color parser understands.
	ctx.clearRect(0, 0, 1, 1);
	ctx.fillRect(0, 0, 1, 1);
	const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data;
	return a === 255
		? `rgb(${r}, ${g}, ${b})`
		: `rgba(${r}, ${g}, ${b}, ${(a / 255).toFixed(3)})`;
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
