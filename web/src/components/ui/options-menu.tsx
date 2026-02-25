import { type LucideIcon, MoreVertical } from "lucide-react";
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export interface OptionsMenuItem {
	label: string;
	icon: LucideIcon;
	onClick: () => void;
	variant?: "default" | "destructive";
}

interface OptionsMenuProps {
	items: OptionsMenuItem[];
	trigger: React.ReactNode;
	side?: "top" | "right" | "bottom" | "left";
	align?: "start" | "center" | "end";
}

export function OptionsMenu({
	items,
	trigger,
	side = "bottom",
	align = "end",
}: OptionsMenuProps) {
	return (
		<DropdownMenu>
			<DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
			<DropdownMenuContent side={side} align={align}>
				{items.map((item) => (
					<DropdownMenuItem
						key={item.label}
						className={
							item.variant === "destructive"
								? "text-destructive focus:text-destructive cursor-pointer"
								: "cursor-pointer"
						}
						onClick={item.onClick}
					>
						<item.icon
							className={`size-4${item.variant === "destructive" ? " text-destructive" : ""}`}
						/>
						<span>{item.label}</span>
					</DropdownMenuItem>
				))}
			</DropdownMenuContent>
		</DropdownMenu>
	);
}
