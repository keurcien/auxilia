import { useCallback, useEffect, useRef, useState } from "react";

export type HitlDecision = "approve" | "reject";

type SubmitOptions = {
	command: { resume: { decisions: { type: HitlDecision }[] } };
	optimisticValues: { messages: unknown[] };
	streamSubgraphs: boolean;
};

type UseHitlApprovalsArgs<TPending extends { id: string }> = {
	isInterrupted: boolean;
	pendingToolCalls: TPending[];
	submit: (input: null, opts: SubmitOptions) => void;
	messages: unknown[];
};

export function useHitlApprovals<TPending extends { id: string }>({
	isInterrupted,
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

		const batchKey = pendingToolCalls.map((tc) => tc.id).join("|");
		if (submittedForBatchRef.current === batchKey) return;
		submittedForBatchRef.current = batchKey;

		const ordered = pendingToolCalls.map((tc) => ({
			type: decisions[tc.id],
		}));
		submit(null, {
			command: { resume: { decisions: ordered } },
			optimisticValues: { messages },
			streamSubgraphs: true,
		});
	}, [isInterrupted, pendingToolCalls, decisions, submit, messages]);

	const recordDecision = useCallback(
		(toolCallId: string, type: HitlDecision) => {
			setDecisions((prev) => ({ ...prev, [toolCallId]: type }));
		},
		[],
	);

	return { decisions, recordDecision };
}
