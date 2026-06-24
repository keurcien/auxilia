/**
 * Extract a user-facing API error message.
 *
 * Backend errors expose `detail`, and axios does not case-transform error
 * bodies. Trust `detail` only for 4xx responses; use the fallback for 5xx,
 * network errors, and unexpected shapes.
 */
export function getApiErrorMessage(error: unknown, fallback: string): string {
	const e = error as {
		status?: number;
		response?: { status?: number; data?: unknown };
	};
	const status = e?.response?.status ?? e?.status;

	if (typeof status === "number" && status >= 400 && status < 500) {
		const data = e.response?.data;
		if (data && typeof data === "object") {
			const detail = (data as { detail?: unknown }).detail;
			if (typeof detail === "string" && detail.trim()) {
				return detail;
			}
		}
	}
	return fallback;
}
