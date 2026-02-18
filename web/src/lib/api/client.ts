import axios from "axios";
import snakecaseKeys from "snakecase-keys";

const isServer = typeof window === "undefined";

// API base URL:
// - Server-side: call backend directly (no proxy needed, avoids localhost resolution issues)
// - Client-side: use Next.js proxy path (hides backend URL from browser)
const getApiBaseUrl = () => {
	if (isServer) {
		return process.env.BACKEND_URL || "http://localhost:8000";
	}
	return "/api/backend";
};

export const API_BASE_URL = getApiBaseUrl();

export const api = axios.create({
	baseURL: API_BASE_URL,
	withCredentials: true,
});

// Fields that should not have their nested keys transformed to snake_case
const PRESERVE_KEYS_FIELDS = ["tools"];

// Recursively transform keys to snake_case while preserving specified fields
function snakecaseKeysWithExclusions(
	obj: unknown,
	excludeFields: string[],
): unknown {
	if (Array.isArray(obj)) {
		return obj.map((item) => snakecaseKeysWithExclusions(item, excludeFields));
	}

	if (obj && typeof obj === "object") {
		const record = obj as Record<string, unknown>;
		const result: Record<string, unknown> = {};

		for (const key of Object.keys(record)) {
			// Convert key from camelCase to snake_case
			const snakeKey = key.replace(
				/[A-Z]/g,
				(letter) => `_${letter.toLowerCase()}`,
			);

			if (excludeFields.includes(key)) {
				result[snakeKey] = record[key];
			} else {
				result[snakeKey] = snakecaseKeysWithExclusions(
					record[key],
					excludeFields,
				);
			}
		}

		return result;
	}

	return obj;
}

api.interceptors.request.use((config) => {
	if (
		config.data &&
		typeof config.data === "object" &&
		!(config.data instanceof FormData)
	) {
		config.data = snakecaseKeysWithExclusions(
			Array.isArray(config.data) ? [...config.data] : { ...config.data },
			PRESERVE_KEYS_FIELDS,
		);
	}
	if (config.params && typeof config.params === "object") {
		config.params = snakecaseKeys(config.params, { deep: true });
	}
	return config;
});

// Recursively transform keys to camelCase while preserving specified fields
function camelcaseKeysWithExclusions(
	obj: unknown,
	excludeFields: string[],
): unknown {
	if (Array.isArray(obj)) {
		return obj.map((item) => camelcaseKeysWithExclusions(item, excludeFields));
	}

	if (obj && typeof obj === "object") {
		const record = obj as Record<string, unknown>;
		const result: Record<string, unknown> = {};

		for (const key of Object.keys(record)) {
			const camelKey = key.replace(/_([a-z])/g, (_, letter) =>
				letter.toUpperCase(),
			);

			if (excludeFields.includes(camelKey)) {
				result[camelKey] = record[key];
			} else {
				result[camelKey] = camelcaseKeysWithExclusions(
					record[key],
					excludeFields,
				);
			}
		}

		return result;
	}

	return obj;
}

api.interceptors.response.use((res) => {
	if (res.data && typeof res.data === "object") {
		res.data = camelcaseKeysWithExclusions(res.data, PRESERVE_KEYS_FIELDS);
	}
	return res;
});
