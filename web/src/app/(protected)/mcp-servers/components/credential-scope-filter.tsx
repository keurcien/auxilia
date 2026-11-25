"use client";

import * as DropdownMenuPrimitive from "@radix-ui/react-dropdown-menu";
import { useState } from "react";
import { Check, ChevronDown, Layers3, UserRound, UsersRound } from "lucide-react";
import { cn } from "@/lib/utils";
import { isPersonalAuth, type MCPServerAuthShape } from "@/types/mcp-servers";

export type CredentialScopeFilter = "all" | "personal" | "shared";

export function parseCredentialScopeFilter(value: string): CredentialScopeFilter {
	return value === "personal" || value === "shared" ? value : "all";
}

/** Personal: each user connects with their own account or secret. Shared:
 * the workspace's credentials, or none, serve everyone. */
export function matchesCredentialScope(
	server: MCPServerAuthShape,
	filter: CredentialScopeFilter,
): boolean {
	if (filter === "all") return true;
	return isPersonalAuth(server) === (filter === "personal");
}

const OPTIONS = [
	{
		value: "all",
		label: "All credentials",
		description: "Personal and shared servers",
		Icon: Layers3,
	},
	{
		value: "personal",
		label: "Personal credentials",
		description: "Each user connects with their own account or key",
		Icon: UserRound,
	},
	{
		value: "shared",
		label: "Shared credentials",
		description: "Configured once by an admin for everyone",
		Icon: UsersRound,
	},
] as const;

export function CredentialScopeFilterDropdown({
	value,
	onChange,
}: {
	value: CredentialScopeFilter;
	onChange: (value: CredentialScopeFilter) => void;
}) {
	const [open, setOpen] = useState(false);
	const selected = OPTIONS.find((option) => option.value === value) ?? OPTIONS[0];

	return (
		<DropdownMenuPrimitive.Root open={open} onOpenChange={setOpen}>
			<DropdownMenuPrimitive.Trigger asChild>
				<button
					type="button"
					className="flex h-8 shrink-0 cursor-pointer items-center gap-2 whitespace-nowrap rounded-[7px] border border-border bg-card px-2.5 text-[12.5px] font-medium text-foreground"
				>
					<selected.Icon className="size-3.5 text-meta" />
					<span>{selected.label}</span>
					<ChevronDown
						className={cn(
							"size-3.5 text-meta transition-transform",
							open && "rotate-180",
						)}
					/>
				</button>
			</DropdownMenuPrimitive.Trigger>

			<DropdownMenuPrimitive.Portal>
				<DropdownMenuPrimitive.Content
					align="start"
					sideOffset={4}
					collisionPadding={16}
					className="z-50 w-[min(300px,calc(100vw-2rem))] rounded-[7px] border border-border bg-card p-1.5 shadow-[0_14px_40px_rgba(16,24,32,0.14)] dark:border-white/10"
				>
					<p className="px-3 pb-1 pt-1 text-[10.5px] font-semibold text-meta">
						Credentials
					</p>
					{OPTIONS.map(({ value: optionValue, label, description, Icon }) => (
						<DropdownMenuPrimitive.Item
							key={optionValue}
							onSelect={() => {
								onChange(optionValue);
							}}
							className="flex w-full cursor-pointer select-none items-center gap-2.5 rounded-[5px] px-3 py-2 text-left outline-none focus:bg-sidebar dark:focus:bg-white/5"
						>
							<Icon className="size-4 shrink-0 text-meta" />
							<span className="min-w-0 flex-1">
								<span className="block text-[12.5px] font-semibold text-foreground">
									{label}
								</span>
								<span className="block text-[10.5px] text-meta">
									{description}
								</span>
							</span>
							{value === optionValue && (
								<Check className="size-3.5 shrink-0 text-petrol" />
							)}
						</DropdownMenuPrimitive.Item>
					))}
				</DropdownMenuPrimitive.Content>
			</DropdownMenuPrimitive.Portal>
		</DropdownMenuPrimitive.Root>
	);
}
