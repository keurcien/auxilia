import { Model } from "@/types/models";

/**
 * Get the default model from the list of available models.
 * Returns the first model from the first provider that has an API key configured.
 */
export function getDefaultModel(models: Model[]): string | undefined {
	if (models.length === 0) {
		return undefined;
	}
	return models[0].id;
}
