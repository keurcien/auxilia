"use client";

import { useRef } from "react";
import * as DropdownMenuPrimitive from "@radix-ui/react-dropdown-menu";
import { Braces, ChevronDown, FileText } from "lucide-react";
import { WorkspaceTopBarButton } from "@/components/layout/workspace-page";
import { cn } from "@/lib/utils";

interface NewSkillChoiceProps {
	onWrite: () => void;
	onImport: (file: File) => void;
	disabled?: boolean;
}

const ACCEPT = ".zip,.skill,.md";

/** The 📄 tile: a skill written here — instructions any agent can follow. */
function WriteTile({ size = 32 }: { size?: number }) {
	return (
		<span
			className="flex shrink-0 items-center justify-center rounded-lg border border-input bg-petrol-tint text-petrol dark:border-white/10 dark:bg-white/10"
			style={{ width: size, height: size }}
		>
			<FileText style={{ width: size * 0.45, height: size * 0.45 }} />
		</span>
	);
}

/** The `{ }` tile: a bundle built elsewhere, usually with scripts. */
function ImportTile({ size = 32 }: { size?: number }) {
	return (
		<span
			className="flex shrink-0 items-center justify-center rounded-lg bg-ink text-panel-terminal"
			style={{ width: size, height: size }}
		>
			<Braces style={{ width: size * 0.42, height: size * 0.42 }} />
		</span>
	);
}

const WRITE_TITLE = "Write a skill";
const WRITE_TEXT =
	"A step-by-step playbook any agent can follow. Name it, describe when to use it, write the procedure.";
const IMPORT_TITLE = "Import a skill";
const IMPORT_TEXT =
	"A SKILL.md, or a .zip bundle with scripts and references from another Agent Skills tool. Scripts only run on agents with code execution.";

/**
 * Two ways into the library, as a menu under one "New" button (design 23a:
 * the menu teaches the split — written here vs. imported, and what an
 * imported bundle's scripts need). The file input lives here so every
 * caller gets the same accept list.
 */
export function NewSkillMenu({ onWrite, onImport, disabled }: NewSkillChoiceProps) {
	const fileInput = useRef<HTMLInputElement>(null);

	return (
		<>
			<input
				ref={fileInput}
				type="file"
				accept={ACCEPT}
				className="hidden"
				onChange={(e) => {
					const file = e.target.files?.[0];
					e.target.value = "";
					if (file) onImport(file);
				}}
			/>
			<DropdownMenuPrimitive.Root>
				<DropdownMenuPrimitive.Trigger asChild>
					<WorkspaceTopBarButton disabled={disabled} className="pr-3.5">
						New skill
						<ChevronDown className="size-3.5 opacity-70" />
					</WorkspaceTopBarButton>
				</DropdownMenuPrimitive.Trigger>
				<DropdownMenuPrimitive.Portal>
					<DropdownMenuPrimitive.Content
						align="end"
						sideOffset={6}
						className={cn(
							"z-50 w-[360px] rounded-[12px] border border-hairline bg-canvas p-2 shadow-[0_12px_32px_-12px_rgba(10,25,30,0.18)] dark:border-white/10 dark:bg-card",
							"data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:slide-in-from-top-1",
							"data-[state=closed]:animate-out data-[state=closed]:fade-out-0",
						)}
					>
						<MenuItem
							tile={<WriteTile />}
							title={WRITE_TITLE}
							text={WRITE_TEXT}
							onSelect={onWrite}
						/>
						<MenuItem
							tile={<ImportTile />}
							title={IMPORT_TITLE}
							text={IMPORT_TEXT}
							onSelect={() => {
								fileInput.current?.click();
							}}
						/>
					</DropdownMenuPrimitive.Content>
				</DropdownMenuPrimitive.Portal>
			</DropdownMenuPrimitive.Root>
		</>
	);
}

function MenuItem({
	tile,
	title,
	text,
	onSelect,
}: {
	tile: React.ReactNode;
	title: string;
	text: string;
	onSelect: () => void;
}) {
	return (
		<DropdownMenuPrimitive.Item
			onSelect={onSelect}
			className="flex cursor-pointer gap-3 rounded-lg px-3 py-2.5 outline-none transition-colors data-[highlighted]:bg-sidebar dark:data-[highlighted]:bg-white/5"
		>
			{tile}
			<span className="min-w-0">
				<span className="block text-[13.5px] font-bold text-foreground">{title}</span>
				<span className="mt-0.5 block text-[12px] leading-[1.45] text-subtle dark:text-muted-foreground">
					{text}
				</span>
			</span>
		</DropdownMenuPrimitive.Item>
	);
}

/**
 * The same two choices as cards — the library's empty state. Teaches the
 * split before the first skill exists.
 */
export function NewSkillChoices({ onWrite, onImport, disabled }: NewSkillChoiceProps) {
	const fileInput = useRef<HTMLInputElement>(null);
	const cardClass =
		"flex flex-1 cursor-pointer items-start gap-3.5 rounded-[12px] border border-border bg-card p-4 text-left transition-colors hover:border-border-hover hover:bg-sidebar disabled:cursor-default disabled:opacity-60 dark:hover:bg-white/5";

	return (
		<div className="flex flex-col gap-3 sm:flex-row">
			<input
				ref={fileInput}
				type="file"
				accept={ACCEPT}
				className="hidden"
				onChange={(e) => {
					const file = e.target.files?.[0];
					e.target.value = "";
					if (file) onImport(file);
				}}
			/>
			<button type="button" className={cardClass} disabled={disabled} onClick={onWrite}>
				<WriteTile size={38} />
				<span className="min-w-0">
					<span className="block text-[14px] font-bold text-foreground">{WRITE_TITLE}</span>
					<span className="mt-1 block text-[12.5px] leading-[1.5] text-subtle dark:text-muted-foreground">
						{WRITE_TEXT}
					</span>
				</span>
			</button>
			<button
				type="button"
				className={cardClass}
				disabled={disabled}
				onClick={() => {
					fileInput.current?.click();
				}}
			>
				<ImportTile size={38} />
				<span className="min-w-0">
					<span className="block text-[14px] font-bold text-foreground">{IMPORT_TITLE}</span>
					<span className="mt-1 block text-[12.5px] leading-[1.5] text-subtle dark:text-muted-foreground">
						{IMPORT_TEXT}{" "}
						<span className="font-mono text-[10.5px] text-meta dark:text-panel-dim">
							.zip · .skill · .md
						</span>
					</span>
				</span>
			</button>
		</div>
	);
}
