import { cookies } from "next/headers";
import { Trigger } from "@/types/triggers";
import TriggerDetail from "@/app/(protected)/triggers/components/trigger-detail";
import * as triggersApi from "@/lib/api/resources/triggers";

interface TriggerPageProps {
	params: Promise<{ id: string }>;
}

export default async function TriggerPage({ params }: TriggerPageProps) {
	const { id } = await params;
	const cookieStore = await cookies();

	const trigger: Trigger = await triggersApi.getTrigger(id, {
		cookie: cookieStore.toString(),
	});

	return <TriggerDetail trigger={trigger} />;
}
