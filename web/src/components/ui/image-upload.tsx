"use client";

import { ImagePlus, Trash2 } from "lucide-react";
import { useEffect, useId, useMemo } from "react";
import { cn } from "@/lib/utils";

export function ImageFilePreview({
	file,
	className,
}: {
	file: File;
	className?: string;
}) {
	const url = useMemo(() => URL.createObjectURL(file), [file]);
	useEffect(
		() => () => {
			URL.revokeObjectURL(url);
		},
		[url],
	);
	// Browser-direct request keeps the session cookie; Next's optimizer does not.
	// eslint-disable-next-line @next/next/no-img-element
	return <img src={url} alt="" className={cn("size-full object-cover", className)} />;
}

interface ImageUploadProps {
	currentUrl?: string | null;
	file: File | null;
	removed?: boolean;
	onFileChange: (file: File | null) => void;
	onRemove: () => void;
	label?: string;
	disabled?: boolean;
	removable?: boolean;
	previewShape?: "circle" | "rounded";
	className?: string;
}

export function ImageUpload({
	currentUrl,
	file,
	removed = false,
	onFileChange,
	onRemove,
	label = "Image",
	disabled = false,
	removable = true,
	previewShape = "rounded",
	className,
}: ImageUploadProps) {
	const inputId = useId();
	const source = !removed ? currentUrl : null;

	return (
		<div className={cn("flex items-center gap-3", className)}>
			<div
				className={cn(
					"flex size-16 shrink-0 items-center justify-center overflow-hidden border border-input bg-hover dark:bg-white/5",
					previewShape === "circle" ? "rounded-full" : "rounded-[14px]",
				)}
			>
				{file ? (
					<ImageFilePreview
						file={file}
						className={previewShape === "circle" ? "rounded-full" : undefined}
					/>
				) : source ? (
					// Browser-direct request keeps the session cookie; Next's optimizer does not.
					// eslint-disable-next-line @next/next/no-img-element
					<img
						src={source}
						alt=""
						className={cn(
							"size-full object-cover",
							previewShape === "circle" && "rounded-full",
						)}
					/>
				) : (
					<ImagePlus className="size-5 text-meta dark:text-panel-dim" />
				)}
			</div>
			<div className="flex min-w-0 flex-col gap-1.5">
				<span className="text-[13px] font-semibold text-foreground">{label}</span>
				<span className="text-[11.5px] text-meta dark:text-panel-dim">
					JPEG, PNG or WebP, cropped to 512×512
				</span>
				<div className="flex items-center gap-2">
					<label
						htmlFor={inputId}
						className={cn(
							"cursor-pointer rounded-[7px] border border-input bg-card px-3 py-1.5 text-[12px] font-semibold text-petrol transition-colors hover:border-border-hover dark:border-white/10 dark:bg-white/[0.03] dark:text-panel-terminal dark:hover:border-white/20",
							disabled && "pointer-events-none opacity-50",
						)}
					>
						{file || source ? "Replace" : "Upload"}
					</label>
					<input
						id={inputId}
						type="file"
						accept="image/jpeg,image/png,image/webp"
						disabled={disabled}
						className="sr-only"
						onChange={(event) => {
							onFileChange(event.target.files?.[0] ?? null);
							event.target.value = "";
						}}
					/>
					{(file || (source && removable)) && (
						<button
							type="button"
							disabled={disabled}
							onClick={onRemove}
							className="flex cursor-pointer items-center gap-1 rounded-[7px] px-2 py-1.5 text-[12px] font-semibold text-destructive transition-colors hover:bg-destructive/10 disabled:pointer-events-none disabled:opacity-50"
						>
							<Trash2 className="size-3" />
							Remove
						</button>
					)}
				</div>
			</div>
		</div>
	);
}
