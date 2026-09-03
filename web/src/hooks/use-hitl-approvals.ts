import { useCallback, useEffect, useRef, useState } from "react";

export type HitlDecision = "approve" | "reject";

/**
 * The `input.respond` payload: one decision per hanging tool call, keyed by
 * tool-call id. With the interrupt id the backend validates the batch against
 * the checkpoint (a stale approval is a 409, not a resume of whatever pends
 * now) and orders the decisions itself.
 */
export type HitlResponse = {
	decisions: { tool_call_id: string; type: HitlDecision }[];
};

type UseHitlApprovalsArgs<TPending extends { id: string }> = {
	/** Stable id of the pending interrupt (live event or thread hydration). */
	interruptId: string | null;
	/** The tool calls the interrupt is waiting on; empty when not interrupted. */
	pendingToolCalls: TPending[];
	/** Resume the run — `stream.respond(response, { interruptId })`. */
	respond: (response: HitlResponse) => void;
};

/**
 * Collects one approve/reject decision per pending tool call and, once the
 * batch is complete, resumes the interrupted run exactly once.
 */
export function useHitlApprovals<TPending extends { id: string }>({
	interruptId,
	pendingToolCalls,
	respond,
}: UseHitlApprovalsArgs<TPending>) {
	const [decisions, setDecisions] = useState<Record<string, HitlDecision>>({});
	const submittedBatch = useRef<string | null>(null);

	useEffect(() => {
		if (pendingToolCalls.length === 0) return;
		if (!pendingToolCalls.every((tc) => decisions[tc.id])) return;

		const batchKey =
			interruptId ?? pendingToolCalls.map((tc) => tc.id).join("|");
		if (submittedBatch.current === batchKey) return;
		submittedBatch.current = batchKey;

		respond({
			decisions: pendingToolCalls.map((tc) => ({
				tool_call_id: tc.id,
				type: decisions[tc.id],
			})),
		});
	}, [interruptId, pendingToolCalls, decisions, respond]);

	const recordDecision = useCallback(
		(toolCallId: string, type: HitlDecision) => {
			setDecisions((prev) => ({ ...prev, [toolCallId]: type }));
		},
		[],
	);

	return { decisions, recordDecision };
}
