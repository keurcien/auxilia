"use client";

import { Button } from "@/components/ui/button";
import Image from "next/image";
import {
	HoverCard,
	HoverCardContent,
	HoverCardTrigger,
} from "@/components/ui/hover-card";
import {
	InputGroup,
	InputGroupAddon,
	InputGroupButton,
	InputGroupTextarea,
} from "@/components/ui/input-group";
import { cn } from "@/lib/utils";
import type { FileUIPart } from "./attachments";
import { PaperclipIcon, XIcon } from "lucide-react";
import { FileIcon } from "@/components/artifacts/file-type-icon";
import { nanoid } from "nanoid";
import {
	type ChangeEvent,
	type ChangeEventHandler,
	type ClipboardEventHandler,
	type ComponentProps,
	createContext,
	type FormEvent,
	type FormEventHandler,
	Fragment,
	type HTMLAttributes,
	type KeyboardEventHandler,
	type PropsWithChildren,
	type ReactNode,
	type RefObject,
	useCallback,
	useContext,
	useEffect,
	useLayoutEffect,
	useMemo,
	useRef,
	useState,
	useSyncExternalStore,
} from "react";

// ============================================================================
// Provider Context & Types
// ============================================================================

export type AttachmentsContext = {
	files: (FileUIPart & { id: string })[];
	add: (files: File[] | FileList) => void;
	remove: (id: string) => void;
	clear: () => void;
	openFileDialog: () => void;
	fileInputRef: RefObject<HTMLInputElement | null>;
};

type TextInputContext = {
	value: string;
	setInput: (v: string) => void;
	setDraft: (key: string, value: string) => void;
	clear: () => void;
	activateDraft: (key: string) => void;
	draftIdentity: () => { key: string | null; revision: number };
	draftValue: (key: string) => string;
	clearDraft: (key: string | null, expectedRevision?: number) => void;
};

export type ModelSelectionContext = {
	value: string | undefined;
	setModel: (v: string | undefined) => void;
};

export type StarterAgentContext = {
	value: { name: string; emoji: string | null } | null;
	set: (v: { name: string; emoji: string | null } | null) => void;
};

export type PromptInputControllerProps = {
	textInput: TextInputContext;
	attachments: AttachmentsContext;
	modelSelection: ModelSelectionContext;
	starterAgent: StarterAgentContext;
	/** INTERNAL: Allows PromptInput to register its file textInput + "open" callback */
	__registerFileInput: (
		ref: RefObject<HTMLInputElement | null>,
		open: () => void,
	) => void;
};

const PromptInputController = createContext<PromptInputControllerProps | null>(
	null,
);
const ProviderAttachmentsContext = createContext<AttachmentsContext | null>(
	null,
);

export const usePromptInputController = () => {
	const ctx = useContext(PromptInputController);
	if (!ctx) {
		throw new Error(
			"Wrap your component inside <PromptInputProvider> to use usePromptInputController().",
		);
	}
	return ctx;
};

/** Select the text draft owned by one conversation before the browser paints. */
export const usePromptInputDraft = (key: string) => {
	const controller = usePromptInputController();
	const activateDraft = controller.textInput.activateDraft;
	useLayoutEffect(() => {
		activateDraft(key);
	}, [activateDraft, key]);
};

// Optional variants (do NOT throw). Useful for dual-mode components.
const useOptionalPromptInputController = () =>
	useContext(PromptInputController);

const useOptionalProviderAttachments = () =>
	useContext(ProviderAttachmentsContext);

export type PromptInputProviderProps = PropsWithChildren<{
	initialInput?: string;
}>;

/**
 * Optional global provider that lifts PromptInput state outside of PromptInput.
 * If you don't use it, PromptInput stays fully self-managed.
 */
export function PromptInputProvider({
	initialInput: initialTextInput = "",
	children,
}: PromptInputProviderProps) {
	// ----- textInput state
	const [textInput, setTextInput] = useState(initialTextInput);
	const textInputRef = useRef(initialTextInput);
	const activeDraftKey = useRef<string | null>(null);
	const activeDraftRevision = useRef(0);
	const nextDraftRevision = useRef(0);
	const drafts = useRef(new Map<string, string>());
	const draftRevisions = useRef(new Map<string, number>());
	const setDraft = useCallback((key: string, value: string) => {
		const revision = ++nextDraftRevision.current;
		if (value) drafts.current.set(key, value);
		else drafts.current.delete(key);
		draftRevisions.current.set(key, revision);
		if (activeDraftKey.current !== key) return;
		textInputRef.current = value;
		activeDraftRevision.current = revision;
		setTextInput(value);
	}, []);
	const setDraftInput = useCallback(
		(value: string) => {
			const key = activeDraftKey.current;
			if (key !== null) {
				setDraft(key, value);
				return;
			}
			textInputRef.current = value;
			activeDraftRevision.current = ++nextDraftRevision.current;
			setTextInput(value);
		},
		[setDraft],
	);
	const clearDraft = useCallback((key: string | null, expectedRevision?: number) => {
		const currentRevision =
			activeDraftKey.current === key
				? activeDraftRevision.current
				: key === null
					? 0
					: (draftRevisions.current.get(key) ?? 0);
		if (
			expectedRevision !== undefined &&
			currentRevision !== expectedRevision
		) {
			return;
		}
		if (key !== null) {
			drafts.current.delete(key);
			draftRevisions.current.delete(key);
		}
		if (activeDraftKey.current !== key) return;
		const revision = ++nextDraftRevision.current;
		textInputRef.current = "";
		activeDraftRevision.current = revision;
		if (key !== null) draftRevisions.current.set(key, revision);
		setTextInput("");
	}, []);
	const clearInput = useCallback(() => {
		clearDraft(activeDraftKey.current);
	}, [clearDraft]);
	const getDraftIdentity = useCallback(
		() => ({
			key: activeDraftKey.current,
			revision: activeDraftRevision.current,
		}),
		[],
	);
	const getDraftValue = useCallback(
		(key: string) =>
			activeDraftKey.current === key
				? textInputRef.current
				: (drafts.current.get(key) ?? ""),
		[],
	);
	const activateDraft = useCallback((key: string) => {
		const previousKey = activeDraftKey.current;
		const current = textInputRef.current;
		if (previousKey !== null && previousKey !== key) {
			if (current) drafts.current.set(previousKey, current);
			else drafts.current.delete(previousKey);
			draftRevisions.current.set(
				previousKey,
				activeDraftRevision.current,
			);
		}
		const next = drafts.current.get(key) ?? "";
		activeDraftKey.current = key;
		activeDraftRevision.current = draftRevisions.current.get(key) ?? 0;
		textInputRef.current = next;
		setTextInput(next);
	}, []);

	// ----- model selection state
	const [selectedModel, setSelectedModel] = useState<string | undefined>(
		undefined,
	);

	// ----- starter agent state (persists agent display info across navigation)
	const [starterAgentData, setStarterAgentData] = useState<{
		name: string;
		emoji: string | null;
	} | null>(null);

	// ----- attachments state (global when wrapped)
	const [attachements, setAttachements] = useState<
		(FileUIPart & { id: string })[]
	>([]);
	const attachmentsRef = useRef(attachements);
	const fileInputRef = useRef<HTMLInputElement | null>(null);
	const openRef = useRef<() => void>(() => {});

	useEffect(() => {
		attachmentsRef.current = attachements;
	}, [attachements]);

	useEffect(
		() => () => {
			for (const file of attachmentsRef.current) {
				if (file.url?.startsWith("blob:")) {
					URL.revokeObjectURL(file.url);
				}
			}
		},
		[],
	);

	const add = useCallback((files: File[] | FileList) => {
		const incoming = Array.from(files);
		if (incoming.length === 0) {
			return;
		}

		setAttachements((prev) =>
			prev.concat(
				incoming.map((file) => ({
					id: nanoid(),
					type: "file" as const,
					url: URL.createObjectURL(file),
					mediaType: file.type,
					filename: file.name,
				})),
			),
		);
	}, []);

	const remove = useCallback((id: string) => {
		setAttachements((prev) => {
			const found = prev.find((f) => f.id === id);
			if (found?.url) {
				URL.revokeObjectURL(found.url);
			}
			return prev.filter((f) => f.id !== id);
		});
	}, []);

	const clear = useCallback(() => {
		setAttachements((prev) => {
			for (const f of prev) {
				if (f.url) {
					URL.revokeObjectURL(f.url);
				}
			}
			return [];
		});
	}, []);

	const openFileDialog = useCallback(() => {
		openRef.current?.();
	}, []);

	const attachments = useMemo<AttachmentsContext>(
		() => ({
			files: attachements,
			add,
			remove,
			clear,
			openFileDialog,
			fileInputRef,
		}),
		[attachements, add, remove, clear, openFileDialog],
	);

	const __registerFileInput = useCallback(
		(ref: RefObject<HTMLInputElement | null>, open: () => void) => {
			fileInputRef.current = ref.current;
			openRef.current = open;
		},
		[],
	);

	const modelSelection = useMemo<ModelSelectionContext>(
		() => ({
			value: selectedModel,
			setModel: setSelectedModel,
		}),
		[selectedModel],
	);

	const starterAgent = useMemo<StarterAgentContext>(
		() => ({
			value: starterAgentData,
			set: setStarterAgentData,
		}),
		[starterAgentData],
	);

	const controller = useMemo<PromptInputControllerProps>(
		() => ({
			textInput: {
				value: textInput,
				setInput: setDraftInput,
				setDraft,
				clear: clearInput,
				activateDraft,
				draftIdentity: getDraftIdentity,
				draftValue: getDraftValue,
				clearDraft,
			},
			attachments,
			modelSelection,
			starterAgent,
			__registerFileInput,
		}),
		[
			textInput,
			setDraft,
			setDraftInput,
			clearInput,
			clearDraft,
			getDraftIdentity,
			getDraftValue,
			activateDraft,
			attachments,
			modelSelection,
			starterAgent,
			__registerFileInput,
		],
	);

	return (
		<PromptInputController.Provider value={controller}>
			<ProviderAttachmentsContext.Provider value={attachments}>
				{children}
			</ProviderAttachmentsContext.Provider>
		</PromptInputController.Provider>
	);
}

// ============================================================================
// Component Context & Hooks
// ============================================================================

const LocalAttachmentsContext = createContext<AttachmentsContext | null>(null);

// True when the surrounding PromptInput has attachments disabled (e.g. the
// selected model can't take files) — lets paste/button handlers opt out too.
const AttachmentsDisabledContext = createContext(false);
const AttachmentsAddContext = createContext<
	((files: File[] | FileList) => void) | null
>(null);

const usePromptInputAttachments = () => {
	// Dual-mode: prefer provider if present, otherwise use local
	const provider = useOptionalProviderAttachments();
	const local = useContext(LocalAttachmentsContext);
	const context = provider ?? local;
	if (!context) {
		throw new Error(
			"usePromptInputAttachments must be used within a PromptInput or PromptInputProvider",
		);
	}
	return context;
};

export type PromptInputAttachmentProps = HTMLAttributes<HTMLDivElement> & {
	data: FileUIPart & { id: string };
	className?: string;
};

export function PromptInputAttachment({
	data,
	className,
	...props
}: PromptInputAttachmentProps) {
	const attachments = usePromptInputAttachments();

	const filename = data.filename || "";

	const mediaType =
		data.mediaType?.startsWith("image/") && data.url ? "image" : "file";
	const isImage = mediaType === "image";

	const attachmentLabel = filename || (isImage ? "Image" : "Attachment");

	return (
		<PromptInputHoverCard>
			<HoverCardTrigger asChild>
				<div
					className={cn(
						"group relative flex h-8 cursor-default select-none items-center gap-1.5 rounded-md border border-border px-1.5 font-medium text-sm transition-all hover:bg-accent hover:text-accent-foreground dark:hover:bg-accent/50",
						className,
					)}
					key={data.id}
					{...props}
				>
					<div className="relative size-5 shrink-0">
						<div className="absolute inset-0 flex size-5 items-center justify-center overflow-hidden rounded bg-background transition-opacity group-hover:opacity-0">
							{isImage ? (
								<Image
									alt={filename || "attachment"}
									className="size-5 object-cover"
									height={20}
									src={data.url}
									width={20}
								/>
							) : (
								<FileIcon
									mimeType={data.mediaType ?? ""}
									className="h-5 w-4"
								/>
							)}
						</div>
						<Button
							aria-label="Remove attachment"
							className="absolute inset-0 size-5 cursor-pointer rounded p-0 opacity-0 transition-opacity group-hover:pointer-events-auto group-hover:opacity-100 [&>svg]:size-2.5"
							onClick={(e) => {
								e.stopPropagation();
								attachments.remove(data.id);
							}}
							type="button"
							variant="ghost"
						>
							<XIcon />
							<span className="sr-only">Remove</span>
						</Button>
					</div>

					<span className="flex-1 truncate">{attachmentLabel}</span>
				</div>
			</HoverCardTrigger>
			<PromptInputHoverCardContent className="w-auto p-2">
				<div className="w-auto space-y-3">
					{isImage && (
						<div className="flex max-h-96 w-96 items-center justify-center overflow-hidden rounded-md border">
							<Image
								alt={filename || "attachment preview"}
								className="max-h-full max-w-full object-contain"
								height={384}
								src={data.url}
								width={448}
							/>
						</div>
					)}
					<div className="flex items-center gap-2.5">
						<div className="min-w-0 flex-1 space-y-1 px-0.5">
							<h4 className="truncate font-semibold text-sm leading-none">
								{filename || (isImage ? "Image" : "Attachment")}
							</h4>
							{data.mediaType && (
								<p className="truncate font-mono text-muted-foreground text-xs">
									{data.mediaType}
								</p>
							)}
						</div>
					</div>
				</div>
			</PromptInputHoverCardContent>
		</PromptInputHoverCard>
	);
}

export type PromptInputAttachmentsProps = Omit<
	HTMLAttributes<HTMLDivElement>,
	"children"
> & {
	children: (attachment: FileUIPart & { id: string }) => ReactNode;
};

export function PromptInputAttachments({
	children,
	className,
	...props
}: PromptInputAttachmentsProps) {
	const attachments = usePromptInputAttachments();

	if (!attachments.files.length) {
		return null;
	}

	return (
		<div
			className={cn(
				"flex flex-wrap items-center gap-2 p-3 animate-in fade-in slide-in-from-top-2 duration-200",
				className,
			)}
			{...props}
		>
			{attachments.files.map((file) => (
				<Fragment key={file.id}>{children(file)}</Fragment>
			))}
		</div>
	);
}

export type PromptInputAddAttachmentButtonProps = Omit<
	PromptInputButtonProps,
	"onClick"
>;

export const PromptInputAddAttachmentButton = ({
	children,
	disabled,
	className,
	...props
}: PromptInputAddAttachmentButtonProps) => {
	const attachments = usePromptInputAttachments();
	const attachmentsDisabled = useContext(AttachmentsDisabledContext);

	return (
		<PromptInputButton
			onClick={() => { attachments.openFileDialog(); }}
			disabled={disabled || attachmentsDisabled}
			className={cn("cursor-pointer", className)}
			{...props}
		>
			{children ?? <PaperclipIcon className="size-4" />}
		</PromptInputButton>
	);
};

export type PromptInputMessage = {
	text?: string;
	files?: FileUIPart[];
};

export type PromptInputProps = Omit<
	HTMLAttributes<HTMLFormElement>,
	"onSubmit" | "onError"
> & {
	accept?: string; // e.g., "image/*" or leave undefined for any
	multiple?: boolean;
	// When true, blocks every attachment path (file dialog, drop, paste).
	disableAttachments?: boolean;
	attachmentsDisabledMessage?: string;
	// When true, accepts drops anywhere on document. Default false (opt-in).
	globalDrop?: boolean;
	// Render a hidden input with given name and keep it in sync for native form posts. Default false.
	syncHiddenInput?: boolean;
	// Minimal constraints
	maxFiles?: number;
	maxFileSize?: number; // bytes
	onError?: (err: {
		code: "max_files" | "max_file_size" | "accept";
		message: string;
	}) => void;
	onSubmit: (
		message: PromptInputMessage,
		event: FormEvent<HTMLFormElement>,
	) => void | Promise<void>;
};

export const PromptInput = ({
	className,
	accept,
	multiple,
	disableAttachments,
	attachmentsDisabledMessage = "This model does not support attachments",
	globalDrop,
	syncHiddenInput,
	maxFiles,
	maxFileSize,
	onError,
	onSubmit,
	children,
	...props
}: PromptInputProps) => {
	// Try to use a provider controller if present
	const controller = useOptionalPromptInputController();
	const usingProvider = !!controller;

	// Refs
	const inputRef = useRef<HTMLInputElement | null>(null);
	const formRef = useRef<HTMLFormElement | null>(null);

	// ----- Drag & drop visual state
	const [isDragActive, setIsDragActive] = useState(false);
	// dragenter/dragleave fire for every child element crossed; count the depth
	// so the overlay doesn't flicker while moving inside the drop zone.
	const dragDepth = useRef(0);

	// ----- Local attachments (only used when no provider)
	const [items, setItems] = useState<(FileUIPart & { id: string })[]>([]);
	const files = usingProvider ? controller.attachments.files : items;

	const openFileDialogLocal = useCallback(() => {
		inputRef.current?.click();
	}, []);

	const matchesAccept = useCallback(
		(f: File) => {
			if (!accept || accept.trim() === "") {
				return true;
			}
			const filename = f.name.toLowerCase();
			return accept.split(",").some((rawPattern) => {
				const pattern = rawPattern.trim().toLowerCase();
				if (!pattern) return false;
				if (pattern.startsWith(".")) return filename.endsWith(pattern);
				if (pattern.endsWith("/*")) {
					return f.type.toLowerCase().startsWith(pattern.slice(0, -1));
				}
				return f.type.toLowerCase() === pattern;
			});
		},
		[accept],
	);

	const addLocal = useCallback(
		(fileList: File[] | FileList) => {
			const incoming = Array.from(fileList);
			const accepted = incoming.filter((f) => matchesAccept(f));
			if (incoming.length && accepted.length === 0) {
				onError?.({
					code: "accept",
					message: "No files match the accepted types.",
				});
				return;
			}
			const withinSize = (f: File) =>
				maxFileSize ? f.size <= maxFileSize : true;
			const sized = accepted.filter(withinSize);
			if (accepted.length > 0 && sized.length === 0) {
				onError?.({
					code: "max_file_size",
					message: "All files exceed the maximum size.",
				});
				return;
			}

			setItems((prev) => {
				const capacity =
					typeof maxFiles === "number"
						? Math.max(0, maxFiles - prev.length)
						: undefined;
				const capped =
					typeof capacity === "number" ? sized.slice(0, capacity) : sized;
				if (typeof capacity === "number" && sized.length > capacity) {
					onError?.({
						code: "max_files",
						message: "Too many files. Some were not added.",
					});
				}
				const next: (FileUIPart & { id: string })[] = [];
				for (const file of capped) {
					next.push({
						id: nanoid(),
						type: "file",
						url: URL.createObjectURL(file),
						mediaType: file.type,
						filename: file.name,
					});
				}
				return prev.concat(next);
			});
		},
		[matchesAccept, maxFiles, maxFileSize, onError],
	);

	const addFiles = usingProvider
		? (fileList: File[] | FileList) => {
				const incoming = Array.from(fileList);
				const accepted = incoming.filter(matchesAccept);
				if (accepted.length !== incoming.length) {
					onError?.({
						code: "accept",
						message: "Some files do not match the accepted types.",
					});
				}
				const sized = accepted.filter(
					(file) => !maxFileSize || file.size <= maxFileSize,
				);
				if (sized.length !== accepted.length) {
					onError?.({
						code: "max_file_size",
						message: "Some files exceed the maximum size.",
					});
				}
				const capacity =
					typeof maxFiles === "number"
						? Math.max(0, maxFiles - files.length)
						: sized.length;
				const capped = sized.slice(0, capacity);
				if (capped.length !== sized.length) {
					onError?.({
						code: "max_files",
						message: "Too many files. Some were not added.",
					});
				}
				if (capped.length > 0) controller.attachments.add(capped);
			}
		: addLocal;
	// Every ingestion path (file dialog, drop, paste) funnels through here.
	const add = disableAttachments ? () => {} : addFiles;

	const remove = usingProvider
		? (id: string) => { controller.attachments.remove(id); }
		: (id: string) =>
				{ setItems((prev) => {
					const found = prev.find((file) => file.id === id);
					if (found?.url) {
						URL.revokeObjectURL(found.url);
					}
					return prev.filter((file) => file.id !== id);
				}); };

	const clear = usingProvider
		? () => { controller.attachments.clear(); }
		: () =>
				{ setItems((prev) => {
					for (const file of prev) {
						if (file.url) {
							URL.revokeObjectURL(file.url);
						}
					}
					return [];
				}); };

	const openFileDialog = usingProvider
		? () => { controller.attachments.openFileDialog(); }
		: openFileDialogLocal;

	// Drop stale attachments if the flag flips on with files already queued
	// (e.g. the user switches to a model that can't take them).
	useEffect(() => {
		if (disableAttachments && files.length > 0) {
			clear();
		}
	});

	// Let provider know about our hidden file input so external menus can call openFileDialog()
	useEffect(() => {
		if (!usingProvider) return;
		controller.__registerFileInput(inputRef, () => inputRef.current?.click());
	}, [usingProvider, controller]);

	// Note: File input cannot be programmatically set for security reasons
	// The syncHiddenInput prop is no longer functional
	useEffect(() => {
		if (syncHiddenInput && inputRef.current && files.length === 0) {
			inputRef.current.value = "";
		}
	}, [files, syncHiddenInput]);

	// Attach drop handlers on nearest form and document (opt-in)
	useEffect(() => {
		const form = formRef.current;
		if (!form) return;

		const onDragOver = (e: DragEvent) => {
			if (e.dataTransfer?.types?.includes("Files")) {
				e.preventDefault();
			}
		};
		const onDrop = (e: DragEvent) => {
			if (e.dataTransfer?.types?.includes("Files")) {
				e.preventDefault();
			}
			if (e.dataTransfer?.files && e.dataTransfer.files.length > 0) {
				add(e.dataTransfer.files);
			}
		};
		form.addEventListener("dragover", onDragOver);
		form.addEventListener("drop", onDrop);
		return () => {
			form.removeEventListener("dragover", onDragOver);
			form.removeEventListener("drop", onDrop);
		};
	}, [add]);

	useEffect(() => {
		if (!globalDrop) return;

		const onDragOver = (e: DragEvent) => {
			if (e.dataTransfer?.types?.includes("Files")) {
				e.preventDefault();
			}
		};
		const onDrop = (e: DragEvent) => {
			if (e.dataTransfer?.types?.includes("Files")) {
				e.preventDefault();
			}
			// Drops on the form itself bubble here too — the form handler
			// already added them, so skip to avoid duplicating attachments.
			if (formRef.current?.contains(e.target as Node)) {
				return;
			}
			if (e.dataTransfer?.files && e.dataTransfer.files.length > 0) {
				add(e.dataTransfer.files);
			}
		};
		document.addEventListener("dragover", onDragOver);
		document.addEventListener("drop", onDrop);
		return () => {
			document.removeEventListener("dragover", onDragOver);
			document.removeEventListener("drop", onDrop);
		};
	}, [add, globalDrop]);

	// Track file-drag presence to surface the drop-zone hint. Scoped to the
	// document when globalDrop is on (any drag anywhere can land here),
	// otherwise to the form only. Tracked even with attachments disabled —
	// the hint then renders as a "not supported" tint instead.
	useEffect(() => {
		const target: EventTarget | null = globalDrop
			? document
			: formRef.current;
		if (!target) {
			return;
		}

		const hasFiles = (e: DragEvent) =>
			Boolean(e.dataTransfer?.types.includes("Files"));
		const onDragEnter = (e: DragEvent) => {
			if (!hasFiles(e)) return;
			dragDepth.current += 1;
			setIsDragActive(true);
		};
		const onDragLeave = (e: DragEvent) => {
			if (!hasFiles(e)) return;
			dragDepth.current = Math.max(0, dragDepth.current - 1);
			if (dragDepth.current === 0) {
				setIsDragActive(false);
			}
		};
		const reset = () => {
			dragDepth.current = 0;
			setIsDragActive(false);
		};

		target.addEventListener("dragenter", onDragEnter as EventListener);
		target.addEventListener("dragleave", onDragLeave as EventListener);
		target.addEventListener("drop", reset);
		// dragend fires on the source when the drag is cancelled (e.g. Esc)
		window.addEventListener("dragend", reset);
		return () => {
			target.removeEventListener("dragenter", onDragEnter as EventListener);
			target.removeEventListener("dragleave", onDragLeave as EventListener);
			target.removeEventListener("drop", reset);
			window.removeEventListener("dragend", reset);
		};
	}, [globalDrop]);

	useEffect(
		() => () => {
			if (!usingProvider) {
				for (const f of files) {
					if (f.url) URL.revokeObjectURL(f.url);
				}
			}
		},
		[usingProvider, files],
	);

	const handleChange: ChangeEventHandler<HTMLInputElement> = (event) => {
		if (event.currentTarget.files) {
			add(event.currentTarget.files);
		}
	};

	const convertBlobUrlToDataUrl = async (url: string): Promise<string> => {
		const response = await fetch(url);
		const blob = await response.blob();
		return new Promise((resolve, reject) => {
			const reader = new FileReader();
			reader.onloadend = () => { resolve(reader.result as string); };
			reader.onerror = reject;
			reader.readAsDataURL(blob);
		});
	};

	const ctx = useMemo<AttachmentsContext>(
		() => ({
			files: files.map((item) => ({ ...item, id: item.id })),
			add,
			remove,
			clear,
			openFileDialog,
			fileInputRef: inputRef,
		}),
		[files, add, remove, clear, openFileDialog],
	);
	const submittingRef = useRef(false);

	const handleSubmit: FormEventHandler<HTMLFormElement> = (event) => {
		event.preventDefault();
		if (submittingRef.current) return;
		submittingRef.current = true;

		const form = event.currentTarget;
		const text = usingProvider
			? controller.textInput.value
			: (() => {
					const formData = new FormData(form);
					return (formData.get("message") as string) || "";
				})();
		const submittedDraft = usingProvider
			? controller.textInput.draftIdentity()
			: { key: null, revision: 0 };

		// Clear the submitted prompt immediately. If submission fails, restore it
		// only when the user has not typed a replacement in the meantime.
		let clearedDraft: { key: string | null; revision: number } | null = null;
		if (usingProvider) {
			controller.textInput.clearDraft(
				submittedDraft.key,
				submittedDraft.revision,
			);
			clearedDraft = controller.textInput.draftIdentity();
		} else {
			form.reset();
		}
		const submittedFiles = [...files];

		void (async () => {
			try {
				const convertedFiles = await Promise.all(
					submittedFiles.map(async ({ id, ...item }) => {
						if (item.url && item.url.startsWith("blob:")) {
							return {
								...item,
								url: await convertBlobUrlToDataUrl(item.url),
							};
						}
						return item;
					}),
				);
				await onSubmit({ text, files: convertedFiles }, event);
				for (const file of submittedFiles) {
					remove(file.id);
				}
			} catch {
				if (usingProvider && text && clearedDraft) {
					const currentDraft = controller.textInput.draftIdentity();
					if (
						currentDraft.key === clearedDraft.key &&
						currentDraft.revision === clearedDraft.revision
					) {
						if (clearedDraft.key !== null) {
							controller.textInput.setDraft(clearedDraft.key, text);
						} else {
							controller.textInput.setInput(text);
						}
					}
				}
			} finally {
				submittingRef.current = false;
			}
		})();
	};

	// Render with or without local provider
	const inner = (
		<AttachmentsAddContext.Provider value={add}>
			<AttachmentsDisabledContext.Provider value={!!disableAttachments}>
			<input
				accept={accept}
				aria-label="Upload files"
				className="hidden"
				multiple={multiple}
				onChange={handleChange}
				ref={inputRef}
				title="Upload files"
				type="file"
			/>
			<form
				ref={formRef}
				className={cn("w-full", className)}
				onSubmit={handleSubmit}
				{...props}
			>
				<InputGroup
					className={cn(
						"overflow-hidden",
						// `!` beats consumer border overrides scoped on the form
						// (e.g. the chat composer's [&>[data-slot=input-group]] rules).
						isDragActive &&
							disableAttachments &&
							"border-destructive! dark:border-destructive!",
					)}
				>
					{children}
					{isDragActive && (
						<div
							className={cn(
								"pointer-events-none absolute inset-0 z-20 flex items-center justify-center rounded-[inherit] transition-colors",
								disableAttachments
									? "bg-destructive/8 dark:bg-destructive/15"
									: "bg-petrol/8 dark:bg-petrol/25",
							)}
						>
							{disableAttachments && (
								<span className="rounded-[4px] border border-destructive/30 bg-card px-3 py-1.5 text-[13px] font-medium text-destructive shadow-sm">
									{attachmentsDisabledMessage}
								</span>
							)}
						</div>
					)}
				</InputGroup>
				</form>
			</AttachmentsDisabledContext.Provider>
		</AttachmentsAddContext.Provider>
	);

	return usingProvider ? (
		inner
	) : (
		<LocalAttachmentsContext.Provider value={ctx}>
			{inner}
		</LocalAttachmentsContext.Provider>
	);
};

export type PromptInputBodyProps = HTMLAttributes<HTMLDivElement>;

export const PromptInputBody = ({
	className,
	...props
}: PromptInputBodyProps) => (
	<div className={cn("contents", className)} {...props} />
);

export type PromptInputTextareaProps = ComponentProps<
	typeof InputGroupTextarea
>;

// Matched on input capability, not width: a narrow desktop window keeps
// Enter to send, while touch keyboards (no Shift+Enter) keep it a line break.
const TOUCH_KEYBOARD_QUERY = "(hover: none) and (pointer: coarse)";

function subscribeTouchKeyboard(onChange: () => void): () => void {
	const query = window.matchMedia(TOUCH_KEYBOARD_QUERY);
	query.addEventListener("change", onChange);
	return () => {
		query.removeEventListener("change", onChange);
	};
}

/** Whether focusing a field would pop up an on-screen keyboard. */
export function hasTouchKeyboard(): boolean {
	return window.matchMedia(TOUCH_KEYBOARD_QUERY).matches;
}

function useTouchKeyboard(): boolean {
	return useSyncExternalStore(subscribeTouchKeyboard, hasTouchKeyboard, () => false);
}

// Safari and Android keyboards report the Enter that confirms a composition
// with keyCode 229 after compositionend, when isComposing is already false.
const IME_PROCESS_KEY_CODE = 229;

export const PromptInputTextarea = ({
	onChange,
	onKeyDown,
	className,
	placeholder = "How can I help you?",
	...props
}: PromptInputTextareaProps) => {
	const controller = useOptionalPromptInputController();
	const attachments = usePromptInputAttachments();
	const attachmentsDisabled = useContext(AttachmentsDisabledContext);
	const addChecked = useContext(AttachmentsAddContext);
	const [isComposing, setIsComposing] = useState(false);
	const touchKeyboard = useTouchKeyboard();

	const handleKeyDown: KeyboardEventHandler<HTMLTextAreaElement> = (e) => {
		// The caller's handler runs first and may claim the key.
		onKeyDown?.(e);
		if (e.defaultPrevented) {
			return;
		}
		if (e.key === "Enter") {
			if (
				isComposing ||
				e.nativeEvent.isComposing ||
				e.nativeEvent.keyCode === IME_PROCESS_KEY_CODE
			) {
				return;
			}
			if (e.shiftKey || touchKeyboard) {
				return;
			}
			e.preventDefault();

			// Check if the submit button is disabled before submitting
			const form = e.currentTarget.form;
			const submitButton = form?.querySelector(
				'button[type="submit"]',
			) as HTMLButtonElement | null;
			if (submitButton?.disabled) {
				return;
			}

			form?.requestSubmit();
		}

		// Remove last attachment when Backspace is pressed and textarea is empty
		if (
			e.key === "Backspace" &&
			e.currentTarget.value === "" &&
			attachments.files.length > 0
		) {
			e.preventDefault();
			const lastAttachment = attachments.files.at(-1);
			if (lastAttachment) {
				attachments.remove(lastAttachment.id);
			}
		}
	};

	const handlePaste: ClipboardEventHandler<HTMLTextAreaElement> = (event) => {
		if (attachmentsDisabled) {
			return;
		}

		const files: File[] = [];

		for (const item of event.clipboardData.items) {
			if (item.kind === "file") {
				const file = item.getAsFile();
				if (file) {
					files.push(file);
				}
			}
		}

		if (files.length > 0) {
			event.preventDefault();
			(addChecked ?? attachments.add)(files);
		}
	};

	const controlledProps = controller
		? {
				value: controller.textInput.value,
				onChange: (e: ChangeEvent<HTMLTextAreaElement>) => {
					controller.textInput.setInput(e.currentTarget.value);
					onChange?.(e);
				},
			}
		: {
				onChange,
			};

	return (
		<InputGroupTextarea
			className={cn("field-sizing-content max-h-48 min-h-16", className)}
			enterKeyHint={touchKeyboard ? "enter" : undefined}
			name="message"
			onCompositionEnd={() => { setIsComposing(false); }}
			onCompositionStart={() => { setIsComposing(true); }}
			onKeyDown={handleKeyDown}
			onPaste={handlePaste}
			placeholder={placeholder}
			{...props}
			{...controlledProps}
		/>
	);
};

export type PromptInputFooterProps = Omit<
	ComponentProps<typeof InputGroupAddon>,
	"align"
>;

export const PromptInputFooter = ({
	className,
	...props
}: PromptInputFooterProps) => (
	<InputGroupAddon
		align="block-end"
		className={cn("justify-between gap-1", className)}
		{...props}
	/>
);

export type PromptInputToolsProps = HTMLAttributes<HTMLDivElement>;

export const PromptInputTools = ({
	className,
	...props
}: PromptInputToolsProps) => (
	<div className={cn("flex gap-1", className)} {...props} />
);

export type PromptInputButtonProps = ComponentProps<typeof InputGroupButton>;

export const PromptInputButton = ({
	variant = "ghost",
	className,
	size = "sm",
	...props
}: PromptInputButtonProps) => (
	<InputGroupButton
		className={cn(className)}
		size={size}
		type="button"
		variant={variant}
		{...props}
	/>
);

type PromptInputHoverCardProps = ComponentProps<typeof HoverCard>;

const PromptInputHoverCard = ({
	openDelay = 0,
	closeDelay = 0,
	...props
}: PromptInputHoverCardProps) => (
	<HoverCard closeDelay={closeDelay} openDelay={openDelay} {...props} />
);

type PromptInputHoverCardContentProps = ComponentProps<
	typeof HoverCardContent
>;

const PromptInputHoverCardContent = ({
	align = "start",
	...props
}: PromptInputHoverCardContentProps) => (
	<HoverCardContent align={align} {...props} />
);
