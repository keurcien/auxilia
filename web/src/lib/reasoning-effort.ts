// Human labels for the canonical effort ladder ("none" reads as Off).
const EFFORT_LABELS = new Map<string, string>([
	["none", "Off"],
	["minimal", "Minimal"],
	["low", "Low"],
	["medium", "Medium"],
	["high", "High"],
	["xhigh", "Extra high"],
	["max", "Max"],
]);

export const effortLabel = (effort: string) =>
	EFFORT_LABELS.get(effort) ?? effort;
