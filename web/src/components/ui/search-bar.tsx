import { Search } from "lucide-react";

interface SearchBarProps {
	placeholder?: string;
	value: string;
	onChange: (value: string) => void;
	className?: string;
}

export function SearchBar({
	placeholder = "Search...",
	value,
	onChange,
	className = "",
}: SearchBarProps) {
	return (
		<div className={`relative ${className}`}>
			<Search className="absolute left-4 top-1/2 -translate-y-1/2 size-4 text-[#A3B5AD] dark:text-white/30" />
			<input
				type="text"
				placeholder={placeholder}
				value={value}
				onChange={(e) => onChange(e.target.value)}
				className="w-full pl-10 pr-4 py-2.5 rounded-full border-[1.5px] border-[#E0E8E4] dark:border-white/10 bg-[#FAFCFB] dark:bg-white/5 text-[14px] font-medium font-[family-name:var(--font-dm-sans)] text-[#1E2D28] dark:text-white placeholder:text-[#A3B5AD] dark:placeholder:text-white/30 focus:outline-none focus:border-[#4CA882] transition-colors"
			/>
		</div>
	);
}
