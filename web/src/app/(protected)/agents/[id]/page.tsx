import { cookies } from "next/headers";
import { Agent } from "@/types/agents";
import AgentDetail from "../components/agent-detail";
import * as agentsApi from "@/lib/api/resources/agents";

interface AgentPageProps {
	params: Promise<{ id: string }>;
	searchParams: Promise<{ edit?: string }>;
}

export default async function AgentPage({
	params,
	searchParams,
}: AgentPageProps) {
	const { id } = await params;
	const { edit } = await searchParams;
	const cookieStore = await cookies();

	const agent: Agent = await agentsApi.getAgent(id, {
		cookie: cookieStore.toString(),
	});

	return (
		<AgentDetail key={agent.id} agent={agent} startInEdit={edit === "1"} />
	);
}
