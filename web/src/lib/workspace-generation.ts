let generation = 0;

export function getWorkspaceGeneration(): number {
	return generation;
}

export function advanceWorkspaceGeneration(): number {
	generation += 1;
	return generation;
}

export function isCurrentWorkspaceGeneration(value: number): boolean {
	return value === generation;
}
