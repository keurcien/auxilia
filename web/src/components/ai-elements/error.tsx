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
				"flex items-start gap-3 p-4 bg-destructive/10 border border-destructive/30 rounded-lg text-wrap break-all",
				className
			)}
		>
			<AlertTriangle className="h-5 w-5 text-destructive flex-shrink-0 mt-0.5" />
			<div className="flex-1 min-w-0">
				<div className="text-sm text-destructive">{children}</div>
			</div>
			{onDismiss && (
				<button
					onClick={onDismiss}
					className="flex-shrink-0 text-destructive/60 hover:text-destructive transition-colors"
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
				"text-xs text-destructive mt-1 opacity-75",
				className
			)}
		>
			{children}
		</div>
	);
};

export { Error, ErrorContent, ErrorDetails };
