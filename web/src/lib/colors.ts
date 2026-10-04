const PASTEL_MAP: Record<string, { pill: string; text: string }> = {
	"#6C5CE7": { pill: "#E4DFFF", text: "#5B4DC7" },
	"#00B894": { pill: "#D0F5EA", text: "#00A381" },
	"#E17055": { pill: "#FFE0D9", text: "#C9604A" },
	"#0984E3": { pill: "#D6EAFF", text: "#0770C2" },
	"#FDCB6E": { pill: "#FFF5CC", text: "#D4A832" },
	"#E84393": { pill: "#FFD6EB", text: "#C7367D" },
	"#9E9E9E": { pill: "#EBEBEB", text: "#757575" },
};

export const AGENT_COLORS = Object.keys(PASTEL_MAP);

// Map-based lookup so callers don't index the object with a dynamic key.
const PASTELS = new Map(Object.entries(PASTEL_MAP));
const DEFAULT_PASTEL = PASTEL_MAP["#9E9E9E"];

export function agentPastel(color?: string | null): { pill: string; text: string } {
	if (!color) return DEFAULT_PASTEL;
	return PASTELS.get(color) ?? { pill: `${color}20`, text: color };
}

export function randomAgentColor(): string {
	return AGENT_COLORS[Math.floor(Math.random() * AGENT_COLORS.length)];
}

export function agentColorBackground(color: string): string {
	const accent = (color ? PASTELS.get(color) : undefined)?.text ?? color;
	return `linear-gradient(145deg, ${color}14, ${accent}10)`;
}

function channelToLinear(channel: number): number {
	const value = channel / 255;
	return value <= 0.04045
		? value / 12.92
		: ((value + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string): number {
	const value = hex.slice(1);
	return (
		0.2126 * channelToLinear(Number.parseInt(value.slice(0, 2), 16)) +
		0.7152 * channelToLinear(Number.parseInt(value.slice(2, 4), 16)) +
		0.0722 * channelToLinear(Number.parseInt(value.slice(4, 6), 16))
	);
}

export function readableAvatarText(background: string): "#172027" | "#FFFFFF" {
	const backgroundLuminance = luminance(background);
	const darkLuminance = luminance("#172027");
	const lightLuminance = 1;
	const darkContrast =
		(backgroundLuminance + 0.05) / (darkLuminance + 0.05);
	const lightContrast = (lightLuminance + 0.05) / (backgroundLuminance + 0.05);
	return darkContrast >= lightContrast ? "#172027" : "#FFFFFF";
}

export function colorFromSeed(seed: string): string {
	let hash = 0;
	for (const character of seed) {
		hash = (hash * 31 + (character.codePointAt(0) ?? 0)) >>> 0;
	}
	return AGENT_COLORS[hash % AGENT_COLORS.length];
}

export function avatarColorStyle(
	color: string | null | undefined,
	seed = "",
): { background: string; color: string; border: string } {
	const normalized = color?.toUpperCase();
	const base =
		normalized && /^#[0-9A-F]{6}$/.test(normalized)
			? normalized
			: colorFromSeed(seed);
	const background = PASTELS.get(base)?.pill ?? base;
	return {
		background,
		color: readableAvatarText(background),
		border: `1px solid ${base}2E`,
	};
}
