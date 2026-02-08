"use client";

import { cn } from "@/lib/utils";

export type ToggleState = "always_allow" | "needs_approval" | "disabled";

const states: { id: ToggleState; icon: "check" | "hand" | "block"; label: string }[] = [
	{ id: "always_allow", icon: "check", label: "Always allow" },
	{ id: "needs_approval", icon: "hand", label: "Needs approval" },
	{ id: "disabled", icon: "block", label: "Disabled" },
];

function CheckIcon() {
	return (
		<svg
			xmlns="http://www.w3.org/2000/svg"
			width="20"
			height="20"
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			strokeWidth="2"
			strokeLinecap="round"
			strokeLinejoin="round"
		>
			<path d="M20 6 9 17l-5-5" />
		</svg>
	);
}

function HandIcon() {
	return (
		<svg
			xmlns="http://www.w3.org/2000/svg"
			width="20"
			height="20"
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			strokeWidth="2"
			strokeLinecap="round"
			strokeLinejoin="round"
		>
			<path d="M18 11V6a2 2 0 0 0-2-2a2 2 0 0 0-2 2" />
			<path d="M14 10V4a2 2 0 0 0-2-2a2 2 0 0 0-2 2v2" />
			<path d="M10 10.5V6a2 2 0 0 0-2-2a2 2 0 0 0-2 2v8" />
			<path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15" />
		</svg>
	);
}

function BlockIcon() {
	return (
		<svg
			xmlns="http://www.w3.org/2000/svg"
			width="20"
			height="20"
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			strokeWidth="2"
			strokeLinecap="round"
			strokeLinejoin="round"
		>
			<circle cx="12" cy="12" r="10" />
			<path d="m4.9 4.9 14.2 14.2" />
		</svg>
	);
}

const iconMap = {
	check: CheckIcon,
	hand: HandIcon,
	block: BlockIcon,
};

interface ThreeStateToggleProps {
	value: ToggleState;
	onChange: (value: ToggleState) => void;
	className?: string;
}

export function ThreeStateToggle({
	value,
	onChange,
	className,
}: ThreeStateToggleProps) {
	const selectedIndex = states.findIndex((s) => s.id === value);

	return (
		<div
			className={cn(
				"relative inline-flex items-center bg-gray-100 dark:bg-neutral-800 rounded-full p-1",
				className,
			)}
		>
			{/* Sliding Background Pill */}
			<div
				className="absolute h-8 w-10 bg-white dark:bg-neutral-600 rounded-full shadow transition-all duration-300 ease-out"
				style={{
					left: `${4 + selectedIndex * 40}px`,
				}}
			/>

			{/* Buttons */}
			{states.map((state) => {
				const Icon = iconMap[state.icon];
				const isSelected = value === state.id;

				return (
					<button
						key={state.id}
						type="button"
						onClick={() => onChange(state.id)}
						className={cn(
							"relative z-10 w-10 h-8 flex items-center justify-center rounded-full",
							"transition-colors duration-200 cursor-pointer",
							isSelected
								? "text-gray-800 dark:text-gray-100"
								: "text-gray-400 dark:text-gray-500 hover:text-gray-500 dark:hover:text-gray-400",
						)}
						aria-label={state.label}
						aria-pressed={isSelected}
					>
						<span className="scale-75">
							<Icon />
						</span>
					</button>
				);
			})}
		</div>
	);
}
