export const PASTEL_MAP: Record<string, { pill: string; text: string }> = {
	"#6C5CE7": { pill: "#E4DFFF", text: "#5B4DC7" },
	"#00B894": { pill: "#D0F5EA", text: "#00A381" },
	"#E17055": { pill: "#FFE0D9", text: "#C9604A" },
	"#0984E3": { pill: "#D6EAFF", text: "#0770C2" },
	"#FDCB6E": { pill: "#FFF5CC", text: "#D4A832" },
	"#E84393": { pill: "#FFD6EB", text: "#C7367D" },
	"#9E9E9E": { pill: "#EBEBEB", text: "#757575" },
};

export const AGENT_COLORS = Object.keys(PASTEL_MAP);

export function randomAgentColor(): string {
	return AGENT_COLORS[Math.floor(Math.random() * AGENT_COLORS.length)];
}

export function agentColorBackground(color: string): string {
	const accent = PASTEL_MAP[color]?.text ?? color;
	return `linear-gradient(145deg, ${color}14, ${accent}10)`;
}
