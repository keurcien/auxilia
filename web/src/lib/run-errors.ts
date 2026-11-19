// Provider failures are stored on the run as "<label>: <sentence>" by the
// backend (app/runtime/model_errors.py). The label picks the title; anything
// else keeps the generic title and shows the raw text.
const RUN_ERROR_TITLES: Record<string, string> = {
	"Context window exceeded": "This conversation is too long for the model",
	"Model rate limit reached": "The model provider is rate limiting requests",
	"Model provider overloaded": "The model provider is overloaded",
	"Model provider error": "The model provider failed to answer",
	"Model provider unreachable": "The model provider could not be reached",
	"Model provider rejected the API key": "The model provider rejected the API key",
	"Model access denied": "This model is not accessible",
	"Model not found": "This model is no longer available",
};

// Runs recorded before the backend mapping carry the raw provider text.
const RAW_CONTEXT_OVERFLOW =
	/prompt is too long|context_length_exceeded|maximum context length/i;

export interface RunErrorDescription {
	title: string;
	detail: string;
	known: boolean;
}

export function describeRunError(error: string): RunErrorDescription {
	const separator = error.indexOf(": ");
	if (separator > 0) {
		const title = RUN_ERROR_TITLES[error.slice(0, separator)];
		if (title) {
			const detail = error.slice(separator + 2);
			return {
				title,
				detail: detail.charAt(0).toUpperCase() + detail.slice(1),
				known: true,
			};
		}
	}
	if (RAW_CONTEXT_OVERFLOW.test(error)) {
		return {
			title: RUN_ERROR_TITLES["Context window exceeded"],
			detail: error,
			known: false,
		};
	}
	return { title: "An error occurred.", detail: error, known: false };
}
