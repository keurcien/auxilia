"use client";

import { useUserStore } from "@/stores/user-store";
import type { WorkspaceRole } from "@/types/users";

const RANK: Record<WorkspaceRole, number> = { member: 0, editor: 1, admin: 2 };

/**
 * Whether the viewer clears a minimum workspace role, with the loading state
 * as a first-class answer rather than an implicit "no".
 *
 * `user` is null both when nobody is signed in *and* while `/auth/me` is in
 * flight, and a plain `user && user.role !== …` check reads the second as the
 * first — so the page renders as though the viewer were allowed, for as long
 * as the request takes. `pending` is what keeps that off the screen.
 *
 * This is presentation only. The API is the gate (`require_editor`,
 * `require_admin`); this just avoids offering an action that will 403.
 */
export function useRoleGate(minimum: WorkspaceRole): "pending" | "allowed" | "denied" {
	const user = useUserStore((state) => state.user);
	const isInitialized = useUserStore((state) => state.isInitialized);
	if (!isInitialized) return "pending";
	if (!user) return "denied";
	return RANK[user.role] >= RANK[minimum] ? "allowed" : "denied";
}
