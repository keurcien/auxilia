"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { DropdownMenuItem } from "@/components/ui/dropdown-menu";

export function ThemeToggle() {
	const { resolvedTheme, setTheme } = useTheme();
	const isDark = resolvedTheme === "dark";

	return (
		<DropdownMenuItem
			onClick={() => setTheme(isDark ? "light" : "dark")}
			className="cursor-pointer"
		>
			{isDark ? (
				<Sun className="mr-2 h-4 w-4" />
			) : (
				<Moon className="mr-2 h-4 w-4" />
			)}
			<span>{isDark ? "Light mode" : "Dark mode"}</span>
		</DropdownMenuItem>
	);
}
