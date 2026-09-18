/**
 * Extract a user-facing API error message.
 *
 * Backend errors expose `detail`, and axios does not case-transform error
 * bodies. Trust `detail` only for 4xx responses; use the fallback for 5xx,
 * network errors, and unexpected shapes.
 *
 * `detail` comes in two shapes. A domain error (`app/exceptions.py`) sends a
 * string. FastAPI's own request validation sends an *array* of
 * `{ loc, msg, type }` — a 422 — and reading only the string shape dropped
 * those on the floor, so a rejected field looked to the user like nothing
 * had happened at all.
 */

interface ValidationItem {
	loc?: unknown;
	msg?: unknown;
}

/** "Value error, must be an https:// URL" -> "must be an https:// URL". */
const clean = (msg: string) => msg.replace(/^Value error,\s*/, "").trim();

function fromValidationArray(detail: unknown[]): string | null {
	const messages = detail
		.filter((item): item is ValidationItem => Boolean(item) && typeof item === "object")
		.map((item) => (typeof item.msg === "string" ? clean(item.msg) : ""))
		.filter(Boolean);
	// Deduplicated: the same rule failing on two fields reads once.
	return messages.length > 0 ? [...new Set(messages)].join("; ") : null;
}

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
			if (Array.isArray(detail)) {
				const message = fromValidationArray(detail);
				if (message) return message;
			}
		}
	}
	return fallback;
}
