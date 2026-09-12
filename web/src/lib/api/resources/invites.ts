/**
 * Invite resource — `/invites/`. Admin-issued invitations (email → pending
 * role). Accepting one is on the auth resource (`acceptInvite`).
 */
import { api } from "@/lib/api/client";
import type { Invite, InviteCreate } from "@/types/users";

export async function listInvites(): Promise<Invite[]> {
	const response = await api.get<Invite[]>("/invites/");
	return response.data;
}

export async function createInvite(payload: InviteCreate): Promise<Invite> {
	const response = await api.post<Invite>("/invites/", payload);
	return response.data;
}

export async function deleteInvite(inviteId: string): Promise<void> {
	await api.delete(`/invites/${inviteId}`);
}
