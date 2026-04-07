"use client";

import { useState } from "react";
import { AlertCircle, AlertTriangle, CheckCircle, Info, X } from "lucide-react";
import { cn } from "@/lib/utils";

type AlertVariant = "error" | "warning" | "success" | "info";

interface VariantConfig {
	border: string;
	iconBg: string;
	iconColor: string;
	text: string;
	dismissHover: string;
	Icon: typeof AlertCircle;
}

function getVariant(variant: AlertVariant): VariantConfig {
	switch (variant) {
		case "error":
			return {
				border: "border-[#F0D0CC] dark:border-[#D45B45]/30",
				iconBg: "bg-[#FDF2F1] dark:bg-[#D45B45]/10",
				iconColor: "text-[#D45B45]",
				text: "text-[#D45B45]",
				dismissHover: "hover:bg-[#FDF2F1] dark:hover:bg-[#D45B45]/10",
				Icon: AlertCircle,
			};
		case "warning":
			return {
				border: "border-[#F0E4C8] dark:border-[#C4930A]/30",
				iconBg: "bg-[#FDF8ED] dark:bg-[#C4930A]/10",
				iconColor: "text-[#C4930A]",
				text: "text-[#9A7400] dark:text-[#C4930A]",
				dismissHover: "hover:bg-[#FDF8ED] dark:hover:bg-[#C4930A]/10",
				Icon: AlertTriangle,
			};
		case "success":
			return {
				border: "border-[#C8E6D8] dark:border-[#3D8B63]/30",
				iconBg: "bg-[#EDF4F0] dark:bg-[#3D8B63]/10",
				iconColor: "text-[#3D8B63]",
				text: "text-[#2D6A4F] dark:text-[#3D8B63]",
				dismissHover: "hover:bg-[#EDF4F0] dark:hover:bg-[#3D8B63]/10",
				Icon: CheckCircle,
			};
		case "info":
			return {
				border: "border-[#C8DAF0] dark:border-[#3B72B8]/30",
				iconBg: "bg-[#EDF2FA] dark:bg-[#3B72B8]/10",
				iconColor: "text-[#3B72B8]",
				text: "text-[#2B5A94] dark:text-[#3B72B8]",
				dismissHover: "hover:bg-[#EDF2FA] dark:hover:bg-[#3B72B8]/10",
				Icon: Info,
			};
	}
}

interface SageAlertProps {
	variant?: AlertVariant;
	message: string;
	dismissible?: boolean;
	className?: string;
}

export function SageAlert({
	variant = "error",
	message,
	dismissible = true,
	className,
}: SageAlertProps) {
	const [visible, setVisible] = useState(true);
	if (!visible) return null;

	const v = getVariant(variant);

	return (
		<div
			className={cn(
				"flex items-center gap-3.5 px-5 py-4 rounded-[18px] bg-white dark:bg-[#1C1C1C] border-[1.5px] animate-in fade-in slide-in-from-bottom-2 duration-300",
				v.border,
				className,
			)}
		>
			<div
				className={cn(
					"shrink-0 w-9 h-9 rounded-full flex items-center justify-center",
					v.iconBg,
				)}
			>
				<v.Icon className={cn("size-[18px]", v.iconColor)} />
			</div>
			<span
				className={cn(
					"flex-1 font-[family-name:var(--font-dm-sans)] text-[14px] font-medium leading-relaxed",
					v.text,
				)}
			>
				{message}
			</span>
			{dismissible && (
				<button
					onClick={() => setVisible(false)}
					className={cn(
						"shrink-0 w-[30px] h-[30px] rounded-full flex items-center justify-center cursor-pointer transition-colors",
						v.dismissHover,
					)}
				>
					<X className={cn("size-3.5", v.iconColor)} />
				</button>
			)}
		</div>
	);
}
