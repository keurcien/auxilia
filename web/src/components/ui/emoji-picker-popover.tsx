"use client";

import type { ReactNode } from "react";
import EmojiPicker, { Theme } from "emoji-picker-react";
import { useTheme } from "next-themes";

import {
	Popover,
	PopoverContent,
	PopoverTrigger,
} from "@/components/ui/popover";

/**
 * Portaled to the body so a dialog or a scroll container never clips it.
 * Selecting an emoji closes the popover and focus returns to the trigger.
 */
export function EmojiPickerPopover({
	open,
	onOpenChange,
	onSelect,
	label,
	header,
	footer,
	children,
}: {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	onSelect: (emoji: string) => void;
	label: string;
	header?: ReactNode;
	footer?: ReactNode;
	children: ReactNode;
}) {
	const { resolvedTheme } = useTheme();

	return (
		<Popover open={open} onOpenChange={onOpenChange}>
			<PopoverTrigger asChild>{children}</PopoverTrigger>
			<PopoverContent
				align="start"
				sideOffset={8}
				aria-label={label}
				onOpenAutoFocus={(event) => {
					event.preventDefault();
				}}
				className="z-[80] w-auto overflow-hidden p-0 shadow-xl"
			>
				{header}
				<EmojiPicker
					autoFocusSearch
					onEmojiClick={(data) => {
						onSelect(data.emoji);
						onOpenChange(false);
					}}
					theme={resolvedTheme === "dark" ? Theme.DARK : Theme.LIGHT}
					skinTonesDisabled
					previewConfig={{ showPreview: false }}
					style={{ border: "none", borderRadius: 0 }}
				/>
				{footer}
			</PopoverContent>
		</Popover>
	);
}
