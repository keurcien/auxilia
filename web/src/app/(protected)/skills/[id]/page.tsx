"use client";
import { useParams } from "next/navigation";
import SkillEditor from "../skill-editor";
export default function SkillPage() {
	const { id } = useParams<{ id: string }>();
	return <SkillEditor id={id} />;
}
