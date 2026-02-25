import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";

interface PageHeaderButtonProps {
	onClick: () => void;
	disabled?: boolean;
	children: React.ReactNode;
}

export default function PageHeaderButton({
	onClick,
	disabled,
	children,
}: PageHeaderButtonProps) {
	return (
		<Button
			className="flex items-center gap-2 py-2.5 md:py-5 bg-[#2A2F2D] text-sm md:text-base font-semibold text-white rounded-[14px] hover:bg-[#363D3A] transition-colors cursor-pointer shadow-[0_4px_14px_rgba(118,181,160,0.14)] border-none"
			onClick={onClick}
			disabled={disabled}
		>
			<Plus className="w-4 h-4" />
			{children}
		</Button>
	);
}
