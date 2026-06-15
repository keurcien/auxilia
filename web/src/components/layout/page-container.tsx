import { cn } from "@/lib/utils";

interface PageContainerProps {
	children: React.ReactNode;
	className?: string;
}

export function PageContainer({ children, className }: PageContainerProps) {
	return (
		<div
			className={cn(
				"mx-auto w-full @min-screen-xl/layout:max-w-6xl",
				className,
			)}
		>
			{children}
		</div>
	);
}
