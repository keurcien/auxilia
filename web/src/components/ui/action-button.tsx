import Link from "next/link";

export type ActionButtonProps = Omit<React.ComponentProps<"button">, "onClick"> & {
	/** Navigates as a real link, so middle-click and Cmd/Ctrl+click open a new tab. */
	href?: string;
	onClick?: React.MouseEventHandler<HTMLElement>;
};

/** A link when `href` is set (and not disabled), a button otherwise, with the same look. */
export function ActionButton({
	href,
	disabled,
	onClick,
	className,
	children,
	type = "button",
	...props
}: ActionButtonProps) {
	if (href && !disabled) {
		return (
			<Link
				href={href}
				onClick={onClick}
				className={className}
				title={props.title}
				aria-label={props["aria-label"]}
			>
				{children}
			</Link>
		);
	}
	return (
		<button
			type={type}
			disabled={disabled}
			onClick={onClick}
			className={className}
			{...props}
		>
			{children}
		</button>
	);
}

/**
 * Click handler for a link whose plain left click acts in place (e.g. an Edit
 * link flipping the page into edit mode without a reload), while middle and
 * modified clicks still open its href in a new tab.
 */
export function onPlainClick(
	action: () => void,
): React.MouseEventHandler<HTMLElement> {
	return (event) => {
		if (
			event.button !== 0 ||
			event.metaKey ||
			event.ctrlKey ||
			event.shiftKey ||
			event.altKey
		) {
			return;
		}
		event.preventDefault();
		action();
	};
}
