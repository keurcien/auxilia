"use client";

import * as React from "react";
import * as DropdownMenuPrimitive from "@radix-ui/react-dropdown-menu";
import { Check, MoreVertical } from "lucide-react";
import { cn } from "@/lib/utils";

export type SageDropdownItem =
	| {
			label: string;
			icon?: React.ReactNode;
			destructive?: boolean;
			separator?: false;
			onClick?: () => void;
			active?: boolean;
	  }
	| { separator: true };

interface SageDropdownMenuProps {
	items: SageDropdownItem[];
	trigger?: React.ReactNode;
	align?: "start" | "end";
	side?: "bottom" | "right" | "left" | "top";
	sideOffset?: number;
	className?: string;
}

export function SageDropdownMenu({
	items,
	trigger,
	align = "end",
	side = "bottom",
	sideOffset = 8,
	className,
}: SageDropdownMenuProps) {
	return (
		<DropdownMenuPrimitive.Root>
			<DropdownMenuPrimitive.Trigger asChild>
				{trigger || (
					<button className="w-10 h-10 rounded-full bg-[#F5F8F6] dark:bg-white/10 flex items-center justify-center cursor-pointer transition-colors hover:bg-[#EDF4F0] dark:hover:bg-white/15 data-[state=open]:bg-[#EDF4F0] dark:data-[state=open]:bg-white/15">
						<MoreVertical className="w-[18px] h-[18px] text-[#6B7F76]" />
					</button>
				)}
			</DropdownMenuPrimitive.Trigger>

			<DropdownMenuPrimitive.Portal>
				<DropdownMenuPrimitive.Content
					side={side}
					align={align}
					sideOffset={sideOffset}
					className={cn(
						"z-50 min-w-[220px] bg-white dark:bg-[#1C1C1C] border-[1.5px] border-[#E0E8E4] dark:border-white/10 rounded-[20px] p-1.5 shadow-[0_8px_24px_-6px_rgba(0,0,0,0.08)] dark:shadow-[0_8px_24px_-6px_rgba(0,0,0,0.3)]",
						"data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-[0.97] data-[state=open]:slide-in-from-top-1",
						"data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-[0.97]",
						className,
					)}
				>
					{items.map((item, i) => {
						if (item.separator) {
							return (
								<DropdownMenuPrimitive.Separator
									key={i}
									className="h-px bg-[#F0F3F2] dark:bg-white/5 mx-2 my-1"
								/>
							);
						}

						return (
							<DropdownMenuPrimitive.Item
								key={i}
								onSelect={item.onClick}
								className={cn(
									"flex items-center gap-3 px-3.5 py-2.5 rounded-[14px] cursor-pointer outline-none transition-colors select-none",
									"font-[family-name:var(--font-dm-sans)] text-[14px] font-medium",
									item.destructive
										? "text-[#D45B45] focus:bg-[#FFF5F3] dark:focus:bg-[#D45B45]/10"
										: "text-[#1E2D28] dark:text-white/90 focus:bg-[#F8FAF9] dark:focus:bg-white/5",
									item.active &&
										!item.destructive &&
										"bg-[#F8FAF9] dark:bg-white/5",
								)}
							>
								{item.icon && (
									<span
										className={cn(
											"shrink-0 [&_svg]:size-[17px]",
											item.destructive
												? "text-[#D45B45]"
												: "text-[#8FA89E]",
										)}
									>
										{item.icon}
									</span>
								)}
								<span>{item.label}</span>
								{item.active && (
									<Check className="ml-auto size-4 shrink-0 text-[#4CA882]" />
								)}
							</DropdownMenuPrimitive.Item>
						);
					})}
				</DropdownMenuPrimitive.Content>
			</DropdownMenuPrimitive.Portal>
		</DropdownMenuPrimitive.Root>
	);
}
