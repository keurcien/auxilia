"use client";

import { PromptInputProvider } from "@/components/ai-elements/prompt-input";

export default function AgentsLayout({
	children,
}: {
	children: React.ReactNode;
}) {
	return <PromptInputProvider>{children}</PromptInputProvider>;
}
