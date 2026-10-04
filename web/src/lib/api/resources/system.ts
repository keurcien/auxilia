import { api } from "@/lib/api/client";

interface VersionResponse {
	version: string;
}

export async function getBackendVersion(
	signal?: AbortSignal,
): Promise<string> {
	const { data } = await api.get<VersionResponse>("/version", { signal });
	return data.version;
}
