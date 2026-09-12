import { cookies } from "next/headers";
import MCPServerDetail from "../components/mcp-server-detail";
import * as mcpServersApi from "@/lib/api/resources/mcp-servers";

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

	const server = await mcpServersApi.getMcpServer(id, {
		cookie: cookieStore.toString(),
	});

	return <MCPServerDetail server={server} initialEdit={edit === "1"} />;
}
