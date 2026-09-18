"use client";

import { useState } from "react";
import { useSkillsStore } from "@/stores/skills-store";
import type { BoundAgent } from "@/types/agents";
import type { Skill, SkillSummary } from "@/types/skills";

interface DeleteGuard {
	skill: SkillSummary;
	agents: BoundAgent[];
}

interface UseDeleteSkillOptions {
	onDeleted?: (skill: SkillSummary) => void;
	onError?: (error: unknown) => void;
}

/**
 * The two-step delete every skills screen shares: a skill in use opens the
 * guard (which agents, no delete), a free one asks for confirmation. The
 * caller renders `SkillInUseDialog` from `guard` and `ConfirmDialog` from
 * `pending`.
 */
export function useDeleteSkill({ onDeleted, onError }: UseDeleteSkillOptions = {}) {
	const deleteSkill = useSkillsStore((state) => state.deleteSkill);
	const [guard, setGuard] = useState<DeleteGuard | null>(null);
	const [pending, setPending] = useState<SkillSummary | null>(null);

	const requestDelete = (skill: SkillSummary | Skill) => {
		if (skill.agentCount > 0) {
			// Summary and detail both carry the agents, so the guard never has
			// to fetch the skill just to name them.
			setGuard({ skill, agents: skill.agents });
			return;
		}
		setPending(skill);
	};

	const confirmDelete = async () => {
		if (!pending) return;
		try {
			await deleteSkill(pending.id);
			onDeleted?.(pending);
		} catch (error) {
			onError?.(error);
			throw error;
		}
	};

	return {
		guard,
		pending,
		requestDelete,
		confirmDelete,
		clearGuard: () => {
			setGuard(null);
		},
		clearPending: () => {
			setPending(null);
		},
	};
}
