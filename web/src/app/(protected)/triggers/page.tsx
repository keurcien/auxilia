"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import TriggerList from "@/app/(protected)/triggers/components/trigger-list";
import { Button } from "@/components/ui/button";
import { PageContainer } from "@/components/layout/page-container";
import { useTriggersStore } from "@/stores/triggers-store";

export default function TriggersPage() {
	const router = useRouter();
	const triggers = useTriggersStore((state) => state.triggers);
	const [view, setView] = useState<"active" | "paused">("active");

	const activeCount = triggers.filter((trigger) => trigger.isActive).length;
	const pausedCount = triggers.length - activeCount;

	const handleCreate = () => {
		router.push("/triggers/new");
	};

	return (
		<PageContainer>
			<div className="flex flex-col gap-5 my-8 sm:flex-row sm:items-start sm:justify-between">
				<div className="min-w-0">
					<h1 className="font-[family-name:var(--font-jakarta-sans)] font-extrabold text-[32px] tracking-[-0.03em] text-[#111111] dark:text-white">
						Triggers
					</h1>
					<p className="mt-1.5 font-[family-name:var(--font-dm-sans)] text-[15px] font-medium text-[#6B7F76] dark:text-muted-foreground">
						Your agents working in the background, on the schedule you choose.
					</p>
				</div>

				<div className="flex items-center gap-3 shrink-0">
					<Button
						className="flex items-center gap-2 px-6! py-3! h-auto! bg-[#111111] dark:bg-white dark:text-[#111111] text-[14px] font-semibold font-[family-name:var(--font-dm-sans)] text-white rounded-full hover:bg-[#222222] dark:hover:bg-gray-100 transition-all cursor-pointer shadow-[0_4px_12px_-2px_rgba(0,0,0,0.15)] border-none whitespace-nowrap"
						onClick={() => {
							handleCreate();
						}}
					>
						<Plus className="w-4 h-4" />
						New trigger
					</Button>
				</div>
			</div>

			<div className="mb-6 inline-flex items-center gap-1 rounded-full bg-[#F0F4F2] dark:bg-white/5 p-1">
				{(
					[
						{ key: "active", label: "Active", count: activeCount },
						{ key: "paused", label: "Paused", count: pausedCount },
					] as const
				).map((tab) => (
					<button
						key={tab.key}
						onClick={() => {
							setView(tab.key);
						}}
						className={`flex items-center gap-1.5 rounded-full px-4 py-1.5 font-[family-name:var(--font-dm-sans)] text-[13.5px] font-semibold cursor-pointer transition-colors ${
							view === tab.key
								? "bg-white dark:bg-white/10 text-[#1E2D28] dark:text-foreground shadow-[0_1px_2px_rgba(30,45,40,0.08)]"
								: "text-[#8FA89E] dark:text-muted-foreground hover:text-[#1E2D28] dark:hover:text-foreground"
						}`}
					>
						{tab.label}
						<span
							className={
								view === tab.key
									? "text-[#3D8B63] dark:text-emerald-400"
									: "text-[#9AA8A1] dark:text-muted-foreground"
							}
						>
							{tab.count}
						</span>
					</button>
				))}
			</div>

			<TriggerList view={view} onCreate={handleCreate} />
		</PageContainer>
	);
}
