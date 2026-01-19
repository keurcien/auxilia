import { Agent } from "@/types/agents";
import AgentEditor from "../components/agent-editor";
import { api } from "@/lib/api/client";

interface AgentPageProps {
	params: Promise<{ id: string }>;
}

export default async function AgentPage({ params }: AgentPageProps) {
	const { id } = await params;

	const agent: Agent = await api.get(`/agents/${id}`).then((res) => {
		return res.data;
	});

	return <AgentEditor agent={agent} />;
}
