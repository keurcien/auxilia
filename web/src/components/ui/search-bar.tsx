import { Search } from "lucide-react";
import { useEffect, useRef } from "react";

interface SearchBarProps {
	placeholder?: string;
	value: string;
	onChange: (value: string) => void;
	className?: string;
	hint?: string;
	focusOnModK?: boolean;
}

export function SearchBar({
	placeholder = "Search...",
	value,
	onChange,
	className = "",
	hint,
	focusOnModK = false,
}: SearchBarProps) {
	const inputRef = useRef<HTMLInputElement>(null);

	useEffect(() => {
		if (!focusOnModK) return;

		const handleKeyDown = (event: KeyboardEvent) => {
			if (
				(event.metaKey || event.ctrlKey) &&
				event.key.toLowerCase() === "k"
			) {
				event.preventDefault();
				const input = inputRef.current;
				if (!input || input.offsetParent === null) return;
				input.focus();
				input.select();
			}
		};

		window.addEventListener("keydown", handleKeyDown);
		return () => {
			window.removeEventListener("keydown", handleKeyDown);
		};
	}, [focusOnModK]);

	return (
		<div className={`relative ${className}`}>
			<Search className="absolute left-3 top-1/2 size-[15px] -translate-y-1/2 text-meta dark:text-panel-dim" />
			<input
				ref={inputRef}
				type="text"
				placeholder={placeholder}
				value={value}
				onChange={(e) => {
					onChange(e.target.value);
				}}
				className={`w-full rounded-[7px] border border-border bg-sidebar py-2 pl-9 ${hint ? "pr-3 lg:pr-12" : "pr-3"} text-[13px] font-medium text-foreground outline-none transition-[border-color,box-shadow] placeholder:text-meta dark:placeholder:text-panel-dim focus:border-petrol focus:shadow-[0_0_0_3px_rgba(22,96,110,0.10)]`}
			/>
			{hint && (
				<kbd className="pointer-events-none absolute right-2.5 top-1/2 hidden -translate-y-1/2 rounded-[4px] border border-rail bg-background px-[5px] py-px font-mono text-[10px] text-meta lg:block dark:border-white/15 dark:bg-white/5 dark:text-panel-body">
					{hint}
				</kbd>
			)}
		</div>
	);
}
