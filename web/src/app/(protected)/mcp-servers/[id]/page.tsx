import { cookies } from "next/headers";
import { MCPServer } from "@/types/mcp-servers";
import MCPServerDetail from "../components/mcp-server-detail";
import { api } from "@/lib/api/client";

interface MCPServerPageProps {
	params: Promise<{ id: string }>;
	searchParams: Promise<{ edit?: string }>;
}

export default async function MCPServerPage({
	params,
	searchParams,
}: MCPServerPageProps) {
	const { id } = await params;
	const { edit } = await searchParams;
	const cookieStore = await cookies();

	const { data: server } = await api.get<MCPServer>(`/mcp-servers/${id}`, {
		headers: { Cookie: cookieStore.toString() },
	});

	return <MCPServerDetail server={server} initialEdit={edit === "1"} />;
}
