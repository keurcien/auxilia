import { cookies } from "next/headers";
import { notFound } from "next/navigation";

import * as projectsApi from "@/lib/api/resources/projects";
import { toApiError } from "@/lib/api/errors";
import type { ProjectDetail } from "@/types/projects";
import ProjectDetailView from "./project-detail";

interface ProjectPageProps {
	params: Promise<{ id: string }>;
}

export default async function ProjectPage({ params }: ProjectPageProps) {
	const { id } = await params;
	const cookieStore = await cookies();
	let detail: ProjectDetail;
	try {
		detail = await projectsApi.getProjectDetail(id, {
			cookie: cookieStore.toString(),
		});
	} catch (error) {
		const status = toApiError(error).status;
		if (status === 403 || status === 404) notFound();
		throw error;
	}

	return <ProjectDetailView key={detail.id} initialDetail={detail} />;
}
