import { useCallback, useEffect, useRef, useState } from "react";

export type HitlDecision = "approve" | "reject";

/**
 * The `input.respond` payload the backend's RunService canonicalizes. In the
 * addressed form (interrupt id + tool-call-keyed decisions) the backend
 * validates the id against the checkpoint (a stale approval is a 409, not a
 * resume of whatever pends now) and orders the decisions itself, so the list
 * is order-free. The positional form is used only when no interrupt id
 * reached the client (pre-id checkpoints).
 */
export type HitlResponse = {
	decisions: { tool_call_id?: string; type: HitlDecision }[];
};

type UseHitlApprovalsArgs<TPending extends { id: string }> = {
	isInterrupted: boolean;
	/** Stable id of the pending interrupt (live SSE or thread rehydrate). */
	interruptId: string | null;
	pendingToolCalls: TPending[];
	/** Resume the run — `stream.respond(response, { interruptId })`. */
	respond: (response: HitlResponse, interruptId: string | null) => void;
};

/**
 * Collects one approve/reject decision per pending tool call and, once the
 * batch is complete, resumes the interrupted run exactly once.
 */
export function useHitlApprovals<TPending extends { id: string }>({
	isInterrupted,
	interruptId,
	pendingToolCalls,
	respond,
}: UseHitlApprovalsArgs<TPending>) {
	const [decisions, setDecisions] = useState<Record<string, HitlDecision>>({});
	const submittedForBatchRef = useRef<string | null>(null);

	useEffect(() => {
		if (!isInterrupted) return;
		if (pendingToolCalls.length === 0) return;
		if (!pendingToolCalls.every((tc) => decisions[tc.id])) return;

		// The interrupt id *is* the batch identity; the joined tool-call ids
		// only approximate it for pre-id checkpoints.
		const batchKey =
			interruptId ?? pendingToolCalls.map((tc) => tc.id).join("|");
		if (submittedForBatchRef.current === batchKey) return;
		submittedForBatchRef.current = batchKey;

		const response: HitlResponse = {
			decisions: pendingToolCalls.map((tc) =>
				interruptId
					? { tool_call_id: tc.id, type: decisions[tc.id] }
					: { type: decisions[tc.id] },
			),
		};
		respond(response, interruptId);
	}, [isInterrupted, interruptId, pendingToolCalls, decisions, respond]);

	const recordDecision = useCallback(
		(toolCallId: string, type: HitlDecision) => {
			setDecisions((prev) => ({ ...prev, [toolCallId]: type }));
		},
		[],
	);

	return { decisions, recordDecision };
}
