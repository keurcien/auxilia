"use client";

import { Plus, Trash2 } from "lucide-react";

interface PersonalHeaderNamesFieldProps {
	names: string[];
	onChange: (names: string[]) => void;
	error?: string;
	inputClassName: string;
	label?: string;
}

/** The header names of a personal custom HTTP server. Only the names live on
 * the server; each user fills in their own values when they connect. */
export function PersonalHeaderNamesField({
	names,
	onChange,
	error,
	inputClassName,
	label = "Personal HTTP headers",
}: PersonalHeaderNamesFieldProps) {
	return (
		<div className="flex flex-col gap-3">
			<div className="flex items-center justify-between gap-3">
				<span className="text-[13px] font-semibold text-foreground">
					{label}
				</span>
				<button
					type="button"
					onClick={() => {
						onChange([...names, ""]);
					}}
					className="inline-flex cursor-pointer items-center gap-1.5 text-[12px] font-semibold text-petrol hover:underline dark:text-panel-terminal"
				>
					<Plus className="size-3.5" />
					Add header
				</button>
			</div>
			{names.map((name, index) => (
				<div key={index} className="grid grid-cols-[minmax(0,1fr)_32px] gap-2">
					<input
						aria-label={`Personal header ${index + 1} name`}
						placeholder="Authorization"
						value={name}
						onChange={(event) => {
							const next = event.target.value;
							onChange(
								names.map((current, position) =>
									position === index ? next : current,
								),
							);
						}}
						className={inputClassName}
					/>
					<button
						type="button"
						aria-label={`Remove personal header ${index + 1}`}
						onClick={() => {
							onChange(names.filter((_, position) => position !== index));
						}}
						className="flex cursor-pointer items-center justify-center rounded-lg text-meta transition-colors hover:bg-destructive/10 hover:text-destructive"
					>
						<Trash2 className="size-4" />
					</button>
				</div>
			))}
			{error && <span className="text-[12.5px] text-destructive">{error}</span>}
		</div>
	);
}
