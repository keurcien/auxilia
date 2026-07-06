import { cookies } from "next/headers";
import { Trigger } from "@/types/triggers";
import TriggerDetail from "@/app/(protected)/triggers/components/trigger-detail";
import { api } from "@/lib/api/client";

interface TriggerPageProps {
	params: Promise<{ id: string }>;
}

export default async function TriggerPage({ params }: TriggerPageProps) {
	const { id } = await params;
	const cookieStore = await cookies();

	const { data: trigger } = await api.get<Trigger>(`/triggers/${id}`, {
		headers: { Cookie: cookieStore.toString() },
	});

	return <TriggerDetail trigger={trigger} />;
}
