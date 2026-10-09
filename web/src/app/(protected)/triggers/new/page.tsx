"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, CalendarClock, Webhook } from "lucide-react";
import TriggerEditor from "@/app/(protected)/triggers/components/trigger-editor";
import { SubpageHeader } from "@/components/layout/subpage-header";
import { useUserStore } from "@/stores/user-store";
import { TriggerType } from "@/types/triggers";

export default function NewTriggerPage() {
	const router = useRouter();
	const currentUser = useUserStore((state) => state.user);
	const userInitialized = useUserStore((state) => state.isInitialized);
	const [triggerType, setTriggerType] = useState<TriggerType | null>(null);

	useEffect(() => {
		if (userInitialized && currentUser?.role === "member") {
			router.replace("/triggers");
		}
	}, [currentUser, router, userInitialized]);

	if (!userInitialized || currentUser?.role === "member") return null;

	if (triggerType) {
		return (
			<TriggerEditor
				triggerType={triggerType}
				onSaved={(trigger) => {
					router.push(`/triggers/${trigger.id}`);
				}}
				onCancel={() => {
					setTriggerType(null);
				}}
			/>
		);
	}

	const choices = [
		{
			type: "schedule" as const,
			title: "Schedule",
			description:
				"Run an agent automatically on a recurring calendar schedule.",
			icon: CalendarClock,
			accent:
				"bg-petrol-tint text-petrol dark:bg-petrol/20 dark:text-panel-terminal",
		},
		{
			type: "webhook" as const,
			title: "Webhook",
			description:
				"Expose a unique URL and run an agent whenever it receives a POST.",
			icon: Webhook,
			accent:
				"bg-petrol-tint text-petrol dark:bg-petrol/20 dark:text-panel-terminal",
		},
	];

	return (
		<div className="flex h-svh min-w-0 flex-1 flex-col bg-background animate-in fade-in duration-300">
			<SubpageHeader
				trail={[
					{ label: "workspace" },
					{ label: "triggers", href: "/triggers" },
					{ label: "new" },
				]}
			/>
			<main className="flex min-h-0 flex-1 items-center justify-center overflow-y-auto px-5 py-12">
				<div className="w-full max-w-[850px] md:-translate-y-10">
					<div className="mb-9 max-w-xl">
						<h1 className="font-[family-name:var(--font-jakarta-sans)] text-[32px] font-bold tracking-[-0.035em] text-foreground">
							How should it start?
						</h1>
						<p className="mt-3 text-[14px] leading-6 text-meta dark:text-panel-dim">
							Choose the event that launches the agent. The trigger type
							cannot be changed after creation.
						</p>
					</div>
					<div className="grid gap-4 md:grid-cols-2">
						{choices.map((choice) => {
							const Icon = choice.icon;
							return (
								<button
									key={choice.type}
									type="button"
									onClick={() => {
										setTriggerType(choice.type);
									}}
									className="group relative flex min-h-[132px] cursor-pointer items-start gap-4 overflow-hidden rounded-2xl border border-border bg-card p-5 text-left transition-all duration-200 hover:-translate-y-0.5 hover:border-petrol/35 hover:shadow-[0_18px_45px_-28px_rgba(16,73,82,0.45)] focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-petrol/15"
								>
									<div
										className={`flex size-11 shrink-0 items-center justify-center rounded-xl ${choice.accent}`}
									>
										<Icon className="size-[21px]" />
									</div>
									<div className="min-w-0 flex-1 pt-0.5">
										<h2 className="text-[19px] font-bold tracking-[-0.02em] text-foreground">
											{choice.title}
										</h2>
										<p className="mt-2 text-[13px] leading-5 text-meta dark:text-panel-dim">
											{choice.description}
										</p>
									</div>
									<div className="flex self-center">
										<span className="flex size-7 items-center justify-center rounded-full bg-sidebar text-meta transition-all group-hover:bg-petrol group-hover:text-white dark:bg-white/5">
											<ArrowRight className="size-3.5" />
										</span>
									</div>
								</button>
							);
						})}
					</div>
				</div>
			</main>
		</div>
	);
}
