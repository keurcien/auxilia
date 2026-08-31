import { useCallback, useEffect, useRef, useState } from "react";

export type HitlDecision = "approve" | "reject";

// The resume payload the backend's RunService canonicalizes. Addressed form
// (interrupt id + tool-call-keyed decisions): the backend validates the id
// against the checkpoint (a stale approval is a 409, not a resume of whatever
// pends now) and orders the decisions itself, so this list is order-free.
// Legacy positional form: only when no interrupt id reached the client.
type ResumePayload =
	| {
			interrupt_id: string;
			decisions: { tool_call_id: string; type: HitlDecision }[];
	  }
	| { decisions: { type: HitlDecision }[] };

type SubmitOptions = {
	command: { resume: ResumePayload };
	optimisticValues: { messages: unknown[] };
	streamSubgraphs: boolean;
};

type UseHitlApprovalsArgs<TPending extends { id: string }> = {
	isInterrupted: boolean;
	/** Stable id of the pending interrupt (live SSE or thread rehydrate). */
	interruptId: string | null;
	pendingToolCalls: TPending[];
	submit: (input: null, opts: SubmitOptions) => void;
	messages: unknown[];
};

export function useHitlApprovals<TPending extends { id: string }>({
	isInterrupted,
	interruptId,
	pendingToolCalls,
	submit,
	messages,
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

		const resume: ResumePayload = interruptId
			? {
					interrupt_id: interruptId,
					decisions: pendingToolCalls.map((tc) => ({
						tool_call_id: tc.id,
						type: decisions[tc.id],
					})),
				}
			: {
					decisions: pendingToolCalls.map((tc) => ({
						type: decisions[tc.id],
					})),
				};
		submit(null, {
			command: { resume },
			optimisticValues: { messages },
			streamSubgraphs: true,
		});
	}, [isInterrupted, interruptId, pendingToolCalls, decisions, submit, messages]);

	const recordDecision = useCallback(
		(toolCallId: string, type: HitlDecision) => {
			setDecisions((prev) => ({ ...prev, [toolCallId]: type }));
		},
		[],
	);

	return { decisions, recordDecision };
}
