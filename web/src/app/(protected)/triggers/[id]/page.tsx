import { cookies } from "next/headers";
import { Trigger } from "@/types/triggers";
import TriggerDetail from "@/app/(protected)/triggers/components/trigger-detail";
import * as triggersApi from "@/lib/api/resources/triggers";

interface TriggerPageProps {
	params: Promise<{ id: string }>;
	searchParams: Promise<{ edit?: string }>;
}

export default async function TriggerPage({
	params,
	searchParams,
}: TriggerPageProps) {
	const { id } = await params;
	const { edit } = await searchParams;
	const cookieStore = await cookies();

	const trigger: Trigger = await triggersApi.getTrigger(id, {
		cookie: cookieStore.toString(),
	});

	return (
		<TriggerDetail
			key={trigger.id}
			trigger={trigger}
			startInEdit={edit === "1"}
		/>
	);
}
