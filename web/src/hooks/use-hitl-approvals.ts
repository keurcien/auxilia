import { useCallback, useEffect, useRef, useState } from "react";

export type HitlDecision = "approve" | "reject";

/**
 * The `input.respond` payload. Addressed form (interrupt id + decisions keyed
 * by tool-call id): the backend validates the batch against the checkpoint (a
 * stale approval is a 409, not a resume of whatever pends now) and orders the
 * decisions itself. Positional form (`{type}` only, in action-request order):
 * used when a pending call has no id — the backend keys such calls
 * `approval-<index>`, which the client cannot reproduce.
 */
export type HitlResponse = {
	decisions: { tool_call_id?: string; type: HitlDecision }[];
};

type UseHitlApprovalsArgs<TPending extends { id: string }> = {
	/** Id of the pending interrupt; `null` forces the positional form. */
	interruptId: string | null;
	/** The tool calls the interrupt is waiting on; empty when not interrupted. */
	pendingToolCalls: TPending[];
	/** Resume the run — `stream.respond(response, { interruptId })`. */
	respond: (response: HitlResponse, interruptId: string | null) => void;
	/** Hold a complete batch until this is true (e.g. another resume is in
	 *  flight — the thread accepts one run at a time). Default: send at once. */
	enabled?: boolean;
};

/**
 * Collects one approve/reject decision per pending tool call and, once the
 * batch is complete, resumes the interrupted run exactly once.
 */
export function useHitlApprovals<TPending extends { id: string }>({
	interruptId,
	pendingToolCalls,
	respond,
	enabled = true,
}: UseHitlApprovalsArgs<TPending>) {
	const [decisions, setDecisions] = useState<Record<string, HitlDecision>>({});
	const submittedBatch = useRef<string | null>(null);

	useEffect(() => {
		if (!enabled || pendingToolCalls.length === 0) return;
		if (!pendingToolCalls.every((tc) => decisions[tc.id])) return;

		const batchKey =
			interruptId ?? pendingToolCalls.map((tc) => tc.id).join("|");
		if (submittedBatch.current === batchKey) return;
		submittedBatch.current = batchKey;

		respond(
			{
				decisions: pendingToolCalls.map((tc) =>
					interruptId
						? { tool_call_id: tc.id, type: decisions[tc.id] }
						: { type: decisions[tc.id] },
				),
			},
			interruptId,
		);
	}, [enabled, interruptId, pendingToolCalls, decisions, respond]);

	const recordDecision = useCallback(
		(toolCallId: string, type: HitlDecision) => {
			setDecisions((prev) => ({ ...prev, [toolCallId]: type }));
		},
		[],
	);

	return { decisions, recordDecision };
}
