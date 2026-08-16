"use client";

import * as React from "react";
import * as DropdownMenuPrimitive from "@radix-ui/react-dropdown-menu";
import { Check, EllipsisVertical } from "lucide-react";
import { cn } from "@/lib/utils";

type DropdownItem =
	| {
			label: string;
			icon?: React.ReactNode;
			destructive?: boolean;
			separator?: false;
			onClick?: () => void;
			active?: boolean;
	  }
	| { separator: true };

interface DropdownMenuProps {
	items: DropdownItem[];
	trigger?: React.ReactNode;
	align?: "start" | "end";
	side?: "bottom" | "right" | "left" | "top";
	sideOffset?: number;
	className?: string;
}

export function DropdownMenu({
	items,
	trigger,
	align = "end",
	side = "bottom",
	sideOffset = 6,
	className,
}: DropdownMenuProps) {
	return (
		<DropdownMenuPrimitive.Root>
			<DropdownMenuPrimitive.Trigger asChild>
				{trigger || (
					<button
						aria-label="More actions"
						className="flex size-7 cursor-pointer items-center justify-center rounded-[7px] text-meta transition-colors hover:bg-hover hover:text-ink data-[state=open]:bg-hover data-[state=open]:text-ink dark:hover:bg-white/10 dark:hover:text-panel-button dark:data-[state=open]:bg-white/10 dark:data-[state=open]:text-panel-button"
					>
						<EllipsisVertical className="size-[15px]" />
					</button>
				)}
			</DropdownMenuPrimitive.Trigger>

			<DropdownMenuPrimitive.Portal>
				<DropdownMenuPrimitive.Content
					side={side}
					align={align}
					sideOffset={sideOffset}
					className={cn(
						"z-50 min-w-[200px] rounded-[10px] border border-hairline bg-canvas p-1 shadow-[0_12px_32px_-12px_rgba(10,25,30,0.18)] dark:border-white/10 dark:bg-card",
						"data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:slide-in-from-top-1",
						"data-[state=closed]:animate-out data-[state=closed]:fade-out-0",
						className,
					)}
				>
					{items.map((item, i) => {
						if (item.separator) {
							return (
								<DropdownMenuPrimitive.Separator
									key={i}
									className="mx-1 my-1 h-px bg-hairline dark:bg-white/10"
								/>
							);
						}

						return (
							<DropdownMenuPrimitive.Item
								key={i}
								onSelect={item.onClick}
								className={cn(
									"flex cursor-pointer select-none items-center gap-2.5 rounded-[6px] px-2.5 py-2 text-[13px] font-medium outline-none transition-colors",
									item.destructive
										? "text-[#B04A3A] focus:bg-[#FBEFED] dark:focus:bg-[#B04A3A]/10"
										: "text-ink focus:bg-hover dark:text-panel-button dark:focus:bg-white/5",
									item.active &&
										!item.destructive &&
										"bg-petrol-tint dark:bg-white/10",
								)}
							>
								{item.icon && (
									<span
										className={cn(
											"shrink-0 [&_svg]:size-[15px]",
											item.destructive ? "text-[#B04A3A]" : "text-label",
										)}
									>
										{item.icon}
									</span>
								)}
								<span>{item.label}</span>
								{item.active && (
									<Check
										className="ml-auto size-3.5 shrink-0 text-petrol dark:text-panel-terminal"
										strokeWidth={3}
									/>
								)}
							</DropdownMenuPrimitive.Item>
						);
					})}
				</DropdownMenuPrimitive.Content>
			</DropdownMenuPrimitive.Portal>
		</DropdownMenuPrimitive.Root>
	);
}
