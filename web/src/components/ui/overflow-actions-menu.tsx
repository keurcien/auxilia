"use client";

import { type ComponentType } from "react";
import { MoreVertical } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { SidebarMenuAction } from "@/components/ui/sidebar";

type OverflowActionTone = "default" | "primary" | "destructive";
type OverflowMenuSide = "top" | "right" | "bottom" | "left";
type OverflowMenuAlign = "start" | "center" | "end";

export interface OverflowActionsMenuItem {
	label: string;
	icon: ComponentType<{ className?: string }>;
	onClick: () => void;
	tone?: OverflowActionTone;
}

interface OverflowActionsMenuProps {
	items: OverflowActionsMenuItem[];
	srLabel: string;
	triggerVariant?: "button" | "sidebar";
	side?: OverflowMenuSide;
	align?: OverflowMenuAlign;
	className?: string;
}

const itemToneClass: Record<OverflowActionTone, string> = {
	default: "",
	primary: "text-primary focus:text-primary",
	destructive: "text-destructive focus:text-destructive",
};

const iconToneClass: Record<OverflowActionTone, string> = {
	default: "",
	primary: "",
	destructive: "text-destructive",
};

export function OverflowActionsMenu({
	items,
	srLabel,
	triggerVariant = "button",
	side = "bottom",
	align = "end",
	className,
}: OverflowActionsMenuProps) {
	return (
		<DropdownMenu>
			<DropdownMenuTrigger asChild>
				{triggerVariant === "sidebar" ? (
					<SidebarMenuAction showOnHover className={cn("cursor-pointer", className)}>
						<MoreVertical className="size-4" />
						<span className="sr-only">{srLabel}</span>
					</SidebarMenuAction>
				) : (
					<Button
						variant="ghost"
						size="icon"
						className={cn("cursor-pointer", className)}
					>
						<MoreVertical className="size-5" />
						<span className="sr-only">{srLabel}</span>
					</Button>
				)}
			</DropdownMenuTrigger>
			<DropdownMenuContent side={side} align={align}>
				{items.map((item, index) => {
					const tone = item.tone ?? "default";
					const Icon = item.icon;

					return (
						<DropdownMenuItem
							key={`${item.label}-${index}`}
							className={cn("cursor-pointer", itemToneClass[tone])}
							onClick={item.onClick}
						>
							<Icon className={cn("size-4", iconToneClass[tone])} />
							<span>{item.label}</span>
						</DropdownMenuItem>
					);
				})}
			</DropdownMenuContent>
		</DropdownMenu>
	);
}
