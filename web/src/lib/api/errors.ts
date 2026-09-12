import { AxiosError } from "axios";

/**
 * The one error shape the API client rejects with.
 *
 * The response interceptor in `client.ts` turns every axios failure into an
 * `ApiError`, so callers branch on `status` / `code` / `detail` and never on
 * `AxiosError` internals. `body` is the backend's JSON body as sent — error
 * bodies are *not* case-converted (the backend's machine-readable keys such as
 * `error` and `model_id` are part of the contract, see `app/exceptions.py`).
 */
export class ApiError extends Error {
	/** HTTP status, or `null` when no response arrived (network, timeout, CORS). */
	readonly status: number | null;
	/** Machine-readable `error` key (`model_unavailable`, `stale_interrupt`), if any. */
	readonly code: string | null;
	/** The backend's human-readable `detail`, if any. */
	readonly detail: string | null;
	/** The raw response body. */
	readonly body: unknown;

	constructor(
		args: {
			status: number | null;
			body?: unknown;
			message?: string;
		},
		options?: { cause?: unknown },
	) {
		const record =
			args.body && typeof args.body === "object"
				? (args.body as Record<string, unknown>)
				: null;
		const detail =
			typeof record?.detail === "string" && record.detail.trim()
				? record.detail
				: null;
		const code = typeof record?.error === "string" ? record.error : null;
		super(
			args.message ??
				detail ??
				(args.status != null
					? `Request failed with status ${args.status}`
					: "Network error"),
			options,
		);
		this.name = "ApiError";
		this.status = args.status;
		this.code = code;
		this.detail = detail;
		this.body = args.body;
	}
}

export function isApiError(error: unknown): error is ApiError {
	return error instanceof ApiError;
}

/**
 * Normalise anything thrown by the API client into an `ApiError`. Idempotent:
 * an `ApiError` passes through; an `AxiosError` is unwrapped; anything else
 * becomes a status-less `ApiError` with the original as `cause`.
 */
export function toApiError(error: unknown): ApiError {
	if (isApiError(error)) return error;
	if (error instanceof AxiosError) {
		return new ApiError(
			{
				status: error.response?.status ?? null,
				body: error.response?.data,
				message:
					error.response?.data && typeof error.response.data === "object"
						? undefined
						: error.message,
			},
			{ cause: error },
		);
	}
	// An axios-shaped plain object (`{ status?, response?: { status?, data? } }`)
	// — what a test double or an already-unwrapped rejection looks like.
	if (error && typeof error === "object" && ("response" in error || "status" in error)) {
		const e = error as {
			status?: unknown;
			message?: unknown;
			data?: unknown;
			response?: { status?: unknown; data?: unknown };
		};
		const status =
			typeof e.response?.status === "number"
				? e.response.status
				: typeof e.status === "number"
					? e.status
					: null;
		return new ApiError(
			{
				status,
				body: e.response?.data ?? e.data,
				message: typeof e.message === "string" ? e.message : undefined,
			},
			{ cause: error },
		);
	}
	return new ApiError(
		{
			status: null,
			message: error instanceof Error ? error.message : undefined,
		},
		{ cause: error },
	);
}

/**
 * Extract a user-facing API error message.
 *
 * Trust the backend's `detail` only for 4xx responses; use the fallback for
 * 5xx, network errors, and unexpected shapes.
 */
export function getApiErrorMessage(error: unknown, fallback: string): string {
	const e = toApiError(error);
	if (e.status != null && e.status >= 400 && e.status < 500 && e.detail) {
		return e.detail;
	}
	return fallback;
}
