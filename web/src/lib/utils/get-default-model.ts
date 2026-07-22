import { Model } from "@/types/models";

/**
 * Get the default model from the list of available models: the workspace
 * default flagged by the backend, else the first available model.
 */
export function getDefaultModel(models: Model[]): string | undefined {
	if (models.length === 0) {
		return undefined;
	}
	return models.find((model) => model.isDefault)?.id ?? models[0].id;
}
