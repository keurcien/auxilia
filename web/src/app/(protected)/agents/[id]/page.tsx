import { cookies } from "next/headers";
import { Agent } from "@/types/agents";
import AgentDetail from "../components/agent-detail";
import { api } from "@/lib/api/client";

interface AgentPageProps {
	params: Promise<{ id: string }>;
}

export default async function AgentPage({ params }: AgentPageProps) {
	const { id } = await params;
	const cookieStore = await cookies();

	const { data: agent } = await api.get<Agent>(`/agents/${id}`, {
		headers: { Cookie: cookieStore.toString() },
	});

	return <AgentDetail agent={agent} />;
}
