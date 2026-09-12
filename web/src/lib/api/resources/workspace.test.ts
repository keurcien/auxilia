import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api/client";
import * as authApi from "./auth";
import * as invitesApi from "./invites";
import * as teamsApi from "./teams";
import * as usersApi from "./users";

vi.mock("@/lib/api/client", () => ({
	api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

beforeEach(() => {
	vi.resetAllMocks();
	vi.mocked(api.get).mockResolvedValue({ data: {} });
	vi.mocked(api.post).mockResolvedValue({ data: {} });
	vi.mocked(api.patch).mockResolvedValue({ data: {} });
	vi.mocked(api.delete).mockResolvedValue({ data: undefined });
});

describe("users resource", () => {
	it("lists with paging, role and search params, unwrapping the page", async () => {
		const page = { items: [], total: 0, limit: 20, offset: 0 };
		vi.mocked(api.get).mockResolvedValue({ data: page });
		const params = { limit: 20, offset: 40, role: "admin" as const, search: "ann" };
		expect(await usersApi.listUsers(params)).toBe(page);
		expect(api.get).toHaveBeenCalledWith("/users", { params });
	});

	it("reads role counts, sets role and team, deletes", async () => {
		vi.mocked(api.get).mockResolvedValue({ data: { total: 3, member: 1, editor: 1, admin: 1 } });
		expect(await usersApi.getRoleCounts()).toEqual({ total: 3, member: 1, editor: 1, admin: 1 });
		expect(api.get).toHaveBeenCalledWith("/users/role-counts");
		await usersApi.setUserRole("u1", "editor");
		expect(api.patch).toHaveBeenCalledWith("/users/u1/role", { role: "editor" });
		await usersApi.setUserTeam("u1", null);
		expect(api.patch).toHaveBeenCalledWith("/users/u1/team", { teamId: null });
		await usersApi.deleteUser("u1");
		expect(api.delete).toHaveBeenCalledWith("/users/u1");
	});
});

describe("teams resource", () => {
	it("lists, creates, updates and deletes on the trailing-slash collection", async () => {
		vi.mocked(api.get).mockResolvedValue({ data: [] });
		expect(await teamsApi.listTeams()).toEqual([]);
		expect(api.get).toHaveBeenCalledWith("/teams/");
		await teamsApi.createTeam({ name: "Ops", color: "#123" });
		expect(api.post).toHaveBeenCalledWith("/teams/", { name: "Ops", color: "#123" });
		await teamsApi.updateTeam("t1", { name: "Ops2", color: null });
		expect(api.patch).toHaveBeenCalledWith("/teams/t1", { name: "Ops2", color: null });
		await teamsApi.deleteTeam("t1");
		expect(api.delete).toHaveBeenCalledWith("/teams/t1");
	});
});

describe("invites resource", () => {
	it("lists, creates and deletes", async () => {
		vi.mocked(api.get).mockResolvedValue({ data: [] });
		expect(await invitesApi.listInvites()).toEqual([]);
		expect(api.get).toHaveBeenCalledWith("/invites/");
		const create = { email: "a@b.c", role: "member" as const, teamId: null };
		vi.mocked(api.post).mockResolvedValue({ data: { id: "i1", inviteUrl: "https://x/i" } });
		expect(await invitesApi.createInvite(create)).toEqual({ id: "i1", inviteUrl: "https://x/i" });
		expect(api.post).toHaveBeenCalledWith("/invites/", create);
		await invitesApi.deleteInvite("i1");
		expect(api.delete).toHaveBeenCalledWith("/invites/i1");
	});
});

describe("auth resource", () => {
	it("covers providers, sign-in/out and the current user", async () => {
		vi.mocked(api.get).mockResolvedValue({ data: { password: true, google: false, setupRequired: false } });
		expect((await authApi.getAuthProviders()).password).toBe(true);
		expect(api.get).toHaveBeenCalledWith("/auth/providers");
		await authApi.signIn("a@b.c", "pw");
		expect(api.post).toHaveBeenCalledWith("/auth/signin", { email: "a@b.c", password: "pw" });
		await authApi.signOut();
		expect(api.post).toHaveBeenCalledWith("/auth/signout");
		await authApi.getCurrentUser();
		expect(api.get).toHaveBeenCalledWith("/auth/me");
	});

	it("covers first-run setup and invite acceptance", async () => {
		vi.mocked(api.get).mockResolvedValue({ data: { setupRequired: true } });
		expect(await authApi.getSetupStatus()).toEqual({ setupRequired: true });
		expect(api.get).toHaveBeenCalledWith("/auth/setup/status");
		const setup = { email: "a@b.c", password: "pw", name: "A" };
		await authApi.completeSetup(setup);
		expect(api.post).toHaveBeenCalledWith("/auth/setup", setup);
		await authApi.getInviteInfo("tok");
		expect(api.get).toHaveBeenCalledWith("/auth/invite/tok");
		const accept = { token: "tok", password: "pw", name: "A" };
		await authApi.acceptInvite(accept);
		expect(api.post).toHaveBeenCalledWith("/auth/invite/accept", accept);
	});

	it("manages personal access tokens", async () => {
		vi.mocked(api.get).mockResolvedValue({ data: [] });
		expect(await authApi.listTokens()).toEqual([]);
		expect(api.get).toHaveBeenCalledWith("/auth/tokens");
		vi.mocked(api.post).mockResolvedValue({ data: { id: "k1", token: "plain" } });
		expect(await authApi.createToken("ci")).toEqual({ id: "k1", token: "plain" });
		expect(api.post).toHaveBeenCalledWith("/auth/tokens", { name: "ci" });
		await authApi.deleteToken("k1");
		expect(api.delete).toHaveBeenCalledWith("/auth/tokens/k1");
	});
});
