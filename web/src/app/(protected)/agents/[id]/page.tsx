import { cookies } from "next/headers";
import { Agent } from "@/types/agents";
import AgentDetail from "../components/agent-detail";
import * as agentsApi from "@/lib/api/resources/agents";

interface AgentPageProps {
	params: Promise<{ id: string }>;
}

export default async function AgentPage({ params }: AgentPageProps) {
	const { id } = await params;
	const cookieStore = await cookies();

	const agent: Agent = await agentsApi.getAgent(id, {
		cookie: cookieStore.toString(),
	});

	return <AgentDetail agent={agent} />;
}
