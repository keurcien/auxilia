"use client";

import { useState } from "react";
import { AlertCircle, AlertTriangle, CheckCircle, Info, X } from "lucide-react";
import { cn } from "@/lib/utils";

type AlertVariant = "error" | "warning" | "success" | "info";

interface VariantConfig {
	container: string;
	dismissHover: string;
	Icon: typeof AlertCircle;
}

function getVariant(variant: AlertVariant): VariantConfig {
	switch (variant) {
		case "error":
			return {
				container: "bg-[#FBEFED] text-[#B04A3A] dark:bg-[#B04A3A]/10",
				dismissHover: "hover:bg-[#B04A3A]/10",
				Icon: AlertCircle,
			};
		case "warning":
			return {
				container: "bg-warning-bg text-warning dark:bg-warning/10",
				dismissHover: "hover:bg-warning/10",
				Icon: AlertTriangle,
			};
		case "success":
			return {
				container: "bg-success-bg text-success dark:bg-success/10",
				dismissHover: "hover:bg-success/10",
				Icon: CheckCircle,
			};
		case "info":
			return {
				container:
					"bg-petrol-tint text-petrol dark:bg-white/5 dark:text-panel-terminal",
				dismissHover: "hover:bg-petrol/10",
				Icon: Info,
			};
	}
}

interface AlertProps {
	variant?: AlertVariant;
	message: string;
	dismissible?: boolean;
	className?: string;
}

export function Alert({
	variant = "error",
	message,
	dismissible = true,
	className,
}: AlertProps) {
	const [visible, setVisible] = useState(true);
	if (!visible) return null;

	const v = getVariant(variant);

	return (
		<div
			className={cn(
				"flex items-center gap-2.5 rounded-[10px] px-4 py-3 animate-in fade-in slide-in-from-bottom-1 duration-200",
				v.container,
				className,
			)}
		>
			<v.Icon className="size-4 shrink-0" />
			<span className="flex-1 text-[13px] font-medium leading-[1.55]">
				{message}
			</span>
			{dismissible && (
				<button
					onClick={() => {
						setVisible(false);
					}}
					aria-label="Dismiss"
					className={cn(
						"flex size-6 shrink-0 cursor-pointer items-center justify-center rounded-[6px] transition-colors",
						v.dismissHover,
					)}
				>
					<X className="size-3.5" />
				</button>
			)}
		</div>
	);
}
