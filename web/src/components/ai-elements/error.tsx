"use client";

import React from "react";
import { cn } from "@/lib/utils";
import { AlertTriangle, X } from "lucide-react";

interface ErrorProps {
	children: React.ReactNode;
	className?: string;
	onDismiss?: () => void;
}

const Error = ({ children, className, onDismiss }: ErrorProps) => {
	return (
		<div
			className={cn(
				"flex items-start gap-3 p-4 bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-800 rounded-lg text-wrap break-all",
				className
			)}
		>
			<AlertTriangle className="h-5 w-5 text-red-500 dark:text-red-400 flex-shrink-0 mt-0.5" />
			<div className="flex-1 min-w-0">
				<div className="text-sm text-red-700 dark:text-red-300">{children}</div>
			</div>
			{onDismiss && (
				<button
					onClick={onDismiss}
					className="flex-shrink-0 text-red-400 hover:text-red-600 dark:text-red-500 dark:hover:text-red-300 transition-colors"
					aria-label="Dismiss error"
				>
					<X className="h-4 w-4" />
				</button>
			)}
		</div>
	);
};

interface ErrorContentProps {
	children: React.ReactNode;
	className?: string;
}

const ErrorContent = ({ children, className }: ErrorContentProps) => {
	return <div className={cn("text-sm font-medium", className)}>{children}</div>;
};

interface ErrorDetailsProps {
	children: React.ReactNode;
	className?: string;
}

const ErrorDetails = ({ children, className }: ErrorDetailsProps) => {
	return (
		<div
			className={cn(
				"text-xs text-red-600 dark:text-red-400 mt-1 opacity-75",
				className
			)}
		>
			{children}
		</div>
	);
};

export { Error, ErrorContent, ErrorDetails };
