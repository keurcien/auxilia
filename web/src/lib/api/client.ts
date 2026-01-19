import axios from "axios";
import camelcaseKeys from "camelcase-keys";
import snakecaseKeys from "snakecase-keys";

export const api = axios.create({
	baseURL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
	withCredentials: true,
});

api.interceptors.request.use((config) => {
	if (
		config.data &&
		typeof config.data === "object" &&
		!(config.data instanceof FormData)
	) {
		config.data = snakecaseKeys(config.data, { deep: true });
	}
	if (config.params && typeof config.params === "object") {
		config.params = snakecaseKeys(config.params, { deep: true });
	}
	return config;
});

api.interceptors.response.use((res) => {
	if (res.data && typeof res.data === "object") {
		res.data = camelcaseKeys(res.data, { deep: true });
	}
	return res;
});
