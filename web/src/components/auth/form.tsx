/** Form primitives matching the AuthShell design (mono uppercase labels, petrol focus ring). */

export function AuthErrorAlert({ error }: { error: string | null }) {
	if (!error) return null;
	return (
		<div role="alert" className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
			{error}
		</div>
	);
}

export function AuthField({
	id,
	label,
	children,
	...inputProps
}: {
	id: string;
	label: string;
	children?: React.ReactNode;
} & Omit<React.InputHTMLAttributes<HTMLInputElement>, "id" | "className">) {
	return (
		<div>
			<label
				htmlFor={id}
				className="mb-[7px] block font-mono text-[10.5px] font-semibold tracking-[0.09em] text-label"
			>
				{label}
			</label>
			<input
				id={id}
				className="w-full rounded-md border border-input bg-canvas px-4 py-3 text-[14.5px] font-medium text-ink outline-none transition-[border-color,box-shadow] placeholder:text-meta focus:border-petrol focus:shadow-[0_0_0_3px_rgba(22,96,110,0.10)]"
				{...inputProps}
			/>
			{children}
		</div>
	);
}

export function AuthSubmitButton({
	disabled,
	children,
}: {
	disabled?: boolean;
	children: React.ReactNode;
}) {
	return (
		<button
			type="submit"
			disabled={disabled}
			className="mt-1.5 cursor-pointer rounded-md bg-ink p-3.5 text-[15px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-60"
		>
			{children}
		</button>
	);
}
