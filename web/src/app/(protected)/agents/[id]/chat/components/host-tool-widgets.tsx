"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { ToolUIPart } from "ai";
import {
	AppWindowIcon,
	BracesIcon,
	CircleDashedIcon,
	Clock3Icon,
	DatabaseIcon,
	ExternalLinkIcon,
	FileSearchIcon,
	PlusIcon,
	SearchIcon,
	ServerIcon,
	WrenchIcon,
} from "lucide-react";

export type HostToolWidgetProps = {
	toolPart: ToolUIPart;
	toolName: string;
	serverName: string;
	className?: string;
};

const MAX_SUMMARY_CHARS = 180;

const isRecord = (value: unknown): value is Record<string, unknown> =>
	typeof value === "object" && value !== null && !Array.isArray(value);

const truncate = (value: string): string => {
	if (value.length <= MAX_SUMMARY_CHARS) {
		return value;
	}

	return `${value.slice(0, MAX_SUMMARY_CHARS).trimEnd()}...`;
};

const readString = (
	record: Record<string, unknown>,
	keys: string[],
): string | undefined => {
	for (const key of keys) {
		const raw = record[key];
		if (typeof raw !== "string") {
			continue;
		}

		const cleaned = raw.trim();
		if (cleaned) {
			return cleaned;
		}
	}

	return undefined;
};

const readNestedValue = (
	value: unknown,
	path: Array<string | number>,
): unknown => {
	let current: unknown = value;

	for (const segment of path) {
		if (typeof segment === "number") {
			if (!Array.isArray(current) || segment < 0 || segment >= current.length) {
				return undefined;
			}
			current = current[segment];
			continue;
		}

		if (!isRecord(current)) {
			return undefined;
		}
		current = current[segment];
	}

	return current;
};

const readNestedString = (
	value: unknown,
	path: Array<string | number>,
): string | undefined => {
	const raw = readNestedValue(value, path);
	if (typeof raw !== "string") {
		return undefined;
	}

	const cleaned = raw.trim();
	return cleaned || undefined;
};

const maybeParseJsonString = (value: unknown): unknown => {
	if (typeof value !== "string") {
		return value;
	}

	const cleaned = value.trim();
	if (!cleaned.startsWith("{") && !cleaned.startsWith("[")) {
		return value;
	}

	try {
		return JSON.parse(cleaned);
	} catch {
		return value;
	}
};

const extractNotionRichText = (value: unknown): string | undefined => {
	if (typeof value === "string") {
		const cleaned = value.trim();
		return cleaned || undefined;
	}

	if (!Array.isArray(value)) {
		return undefined;
	}

	const text = value
		.map((entry) => {
			if (!isRecord(entry)) {
				return "";
			}

			return (
				readString(entry, ["plain_text"]) ??
				readNestedString(entry, ["text", "content"]) ??
				""
			);
		})
		.join("")
		.trim();

	return text || undefined;
};

const toInlineValue = (value: unknown): string => {
	if (value === null || value === undefined) return "null";

	if (typeof value === "string") {
		if (!value.trim()) return '"(empty)"';
		return value.length > 36 ? `"${value.slice(0, 36)}..."` : `"${value}"`;
	}

	if (typeof value === "number" || typeof value === "boolean") return String(value);
	if (Array.isArray(value)) return `list(${value.length})`;
	if (typeof value === "object") return "object";

	return typeof value;
};

const summarizePayload = (payload: unknown): string => {
	if (payload === null || payload === undefined) return "No data yet.";

	if (typeof payload === "string") {
		return truncate(payload.trim() || "(empty string)");
	}

	if (typeof payload === "number" || typeof payload === "boolean") {
		return String(payload);
	}

	if (Array.isArray(payload)) {
		if (payload.length === 0) return "Empty list.";

		const preview = payload
			.slice(0, 3)
			.map((entry) => toInlineValue(entry))
			.join(", ");
		const suffix = payload.length > 3 ? `, +${payload.length - 3} more` : "";

		return truncate(`${preview}${suffix}`);
	}

	if (typeof payload === "object") {
		const entries = Object.entries(payload as Record<string, unknown>);
		if (entries.length === 0) return "Empty object.";

		const preview = entries
			.slice(0, 4)
			.map(([key, value]) => `${key}: ${toInlineValue(value)}`)
			.join(", ");
		const suffix = entries.length > 4 ? `, +${entries.length - 4} more` : "";

		return truncate(`${preview}${suffix}`);
	}

	return truncate(String(payload));
};

const getStateLabel = (state: ToolUIPart["state"]): string => {
	switch (state) {
		case "input-streaming":
		case "input-available":
			return "Running";
		case "approval-requested":
			return "Needs approval";
		case "approval-responded":
			return "Approval received";
		case "output-available":
			return "Complete";
		case "output-error":
		case "output-denied":
			return "Failed";
		default:
			return state;
	}
};

const getBadgeClassName = (state: ToolUIPart["state"]): string => {
	switch (state) {
		case "output-available":
			return "border-emerald-200 bg-emerald-50 text-emerald-700";
		case "output-error":
		case "output-denied":
			return "border-red-200 bg-red-50 text-red-700";
		case "approval-requested":
			return "border-amber-200 bg-amber-50 text-amber-700";
		default:
			return "border-border bg-muted text-foreground";
	}
};

const getOutputSummary = (toolPart: ToolUIPart): string => {
	if (toolPart.errorText) {
		return truncate(toolPart.errorText);
	}

	if (toolPart.state === "approval-requested") {
		return "Waiting for user approval before executing this tool.";
	}

	if (
		toolPart.state === "input-streaming" ||
		toolPart.state === "input-available"
	) {
		return "Tool call is still running.";
	}

	if (
		toolPart.state === "approval-responded" &&
		toolPart.approval?.approved === false
	) {
		return "Tool execution was rejected by user.";
	}

	if (toolPart.output === undefined || toolPart.output === null) {
		return "No output available yet.";
	}

	return summarizePayload(toolPart.output);
};

type NotionPageInfo = {
	title: string;
	url?: string;
	summary?: string;
	lastEdited?: string;
	pageId?: string;
	icon?: string;
};

type NotionDatabaseProperty = {
	name: string;
	type: string;
};

type NotionDatabaseInfo = {
	title: string;
	url?: string;
	description?: string;
	lastEdited?: string;
	databaseId?: string;
	parentLabel?: string;
	icon?: string;
	properties: NotionDatabaseProperty[];
};

const formatPropertyTypeLabel = (type: string): string =>
	type.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());

const getPropertyPreviewValue = (
	type: string,
	rowIndex: number,
	isFirstColumn: boolean,
): string => {
	if (isFirstColumn) {
		return rowIndex === 0 ? "Untitled" : `Row ${rowIndex + 1}`;
	}

	switch (type) {
		case "number":
			return rowIndex === 0 ? "0" : "";
		case "checkbox":
			return rowIndex === 0 ? "☐" : "";
		case "select":
		case "multi_select":
			return rowIndex === 0 ? "Select..." : "";
		case "date":
			return rowIndex === 0 ? "Pick a date" : "";
		case "status":
			return rowIndex === 0 ? "Not started" : "";
		case "relation":
			return rowIndex === 0 ? "Link page" : "";
		default:
			return rowIndex === 0 ? "Empty" : "";
	}
};

const pickFirstRecord = (value: unknown): Record<string, unknown> | undefined => {
	if (isRecord(value)) {
		return value;
	}

	if (Array.isArray(value)) {
		return value.find((entry): entry is Record<string, unknown> => isRecord(entry));
	}

	return undefined;
};

const extractTitleFromProperties = (
	properties: unknown,
): string | undefined => {
	if (!isRecord(properties)) {
		return undefined;
	}

	for (const property of Object.values(properties)) {
		if (!isRecord(property)) {
			continue;
		}

		const propertyType =
			typeof property.type === "string" ? property.type : undefined;
		if (propertyType !== "title") {
			continue;
		}

		const title =
			readNestedString(property, ["title", 0, "plain_text"]) ??
			readNestedString(property, ["title", 0, "text", "content"]);
		if (title) {
			return title;
		}
	}

	return undefined;
};

const extractParentLabel = (parent: unknown): string | undefined => {
	if (!isRecord(parent)) {
		return undefined;
	}

	const type = readString(parent, ["type"]);
	if (type === "workspace") {
		return "Parent: Workspace";
	}

	if (type) {
		const nested = parent[type];
		if (isRecord(nested)) {
			const nestedId =
				readString(nested, ["id", "page_id", "database_id", "block_id"]) ??
				readString(parent, ["page_id", "database_id", "block_id"]);
			if (nestedId) {
				return `Parent: ${type} (${getCompactPageId(nestedId) ?? nestedId})`;
			}
			return `Parent: ${type}`;
		}

		if (typeof nested === "string" && nested.trim()) {
			return `Parent: ${type} (${getCompactPageId(nested) ?? nested})`;
		}

		return `Parent: ${type}`;
	}

	const fallbackId = readString(parent, ["page_id", "database_id", "block_id"]);
	if (fallbackId) {
		return `Parent: ${getCompactPageId(fallbackId) ?? fallbackId}`;
	}

	return undefined;
};

const extractRichTextFromProperties = (
	properties: unknown,
): string | undefined => {
	if (!isRecord(properties)) {
		return undefined;
	}

	for (const property of Object.values(properties)) {
		if (!isRecord(property)) {
			continue;
		}

		const propertyType =
			typeof property.type === "string" ? property.type : undefined;
		if (propertyType !== "rich_text") {
			continue;
		}

		const richText =
			readNestedString(property, ["rich_text", 0, "plain_text"]) ??
			readNestedString(property, ["rich_text", 0, "text", "content"]);
		if (richText) {
			return richText;
		}
	}

	return undefined;
};

const normalizeHttpUrl = (value: string | undefined): string | undefined => {
	if (!value) {
		return undefined;
	}

	try {
		const parsed = new URL(value);
		if (parsed.protocol === "http:" || parsed.protocol === "https:") {
			return parsed.toString();
		}
		return undefined;
	} catch {
		return undefined;
	}
};

const buildNotionPageUrlFromId = (pageId: string | undefined): string | undefined => {
	if (!pageId) {
		return undefined;
	}

	const normalized = pageId.replace(/-/g, "");
	if (!/^[a-fA-F0-9]{32}$/.test(normalized)) {
		return undefined;
	}

	return `https://www.notion.so/${normalized}`;
};

const extractNotionPageRecord = (output: unknown): Record<string, unknown> | null => {
	const parsedOutput = maybeParseJsonString(output);

	if (Array.isArray(parsedOutput)) {
		return (
			parsedOutput.find((entry): entry is Record<string, unknown> =>
				isRecord(entry),
			) ?? null
		);
	}

	if (!isRecord(parsedOutput)) {
		return null;
	}

	const fromResults = pickFirstRecord(parsedOutput.results);
	if (fromResults) {
		return fromResults;
	}

	for (const key of ["result", "page", "data", "item", "record"]) {
		const nested = pickFirstRecord(parsedOutput[key]);
		if (nested) {
			const nestedResults = pickFirstRecord(nested.results);
			return nestedResults ?? nested;
		}
	}

	return parsedOutput;
};

const extractNotionPageInfo = (output: unknown): NotionPageInfo | null => {
	const page = extractNotionPageRecord(output);
	if (!page) {
		return null;
	}

	const pageId = readString(page, ["id", "page_id", "pageId"]);
	const url =
		normalizeHttpUrl(
			readString(page, [
				"url",
				"public_url",
				"publicUrl",
				"web_url",
				"webUrl",
				"page_url",
				"pageUrl",
				"href",
				"link",
			]),
		) ?? buildNotionPageUrlFromId(pageId);

	const title =
		readString(page, ["title", "name", "page_title", "pageTitle"]) ??
		extractTitleFromProperties(page.properties) ??
		"Notion page";

	const summary =
		readString(page, [
			"summary",
			"snippet",
			"excerpt",
			"description",
			"text",
			"content",
		]) ??
		readNestedString(page, ["rich_text", 0, "plain_text"]) ??
		extractRichTextFromProperties(page.properties);

	const icon =
		readString(page, ["emoji", "iconEmoji"]) ??
		readNestedString(page, ["icon", "emoji"]);

	const lastEdited = readString(page, [
		"last_edited_time",
		"lastEditedTime",
		"updated_at",
		"updatedAt",
	]);

	return { title, url, summary, lastEdited, pageId, icon };
};

const extractNotionDatabaseRecord = (
	output: unknown,
): Record<string, unknown> | null => {
	const parsedOutput = maybeParseJsonString(output);

	if (Array.isArray(parsedOutput)) {
		const found = parsedOutput.find((entry): entry is Record<string, unknown> => {
			if (!isRecord(entry)) {
				return false;
			}
			return (
				readString(entry, ["object"]) === "database" ||
				isRecord(entry.properties)
			);
		});
		return found ?? null;
	}

	if (!isRecord(parsedOutput)) {
		return null;
	}

	const objectType = readString(parsedOutput, ["object"]);
	if (objectType === "database" || isRecord(parsedOutput.properties)) {
		return parsedOutput;
	}

	const fromResults = pickFirstRecord(parsedOutput.results);
	if (fromResults) {
		return fromResults;
	}

	for (const key of [
		"database",
		"created_database",
		"createdDatabase",
		"result",
		"data",
		"item",
		"record",
	]) {
		const nested = pickFirstRecord(parsedOutput[key]);
		if (nested) {
			const nestedResults = pickFirstRecord(nested.results);
			return nestedResults ?? nested;
		}
	}

	return parsedOutput;
};

const extractNotionDatabaseInfo = (output: unknown): NotionDatabaseInfo | null => {
	const database = extractNotionDatabaseRecord(output);
	if (!database) {
		return null;
	}

	const databaseId = readString(database, ["id", "database_id", "databaseId"]);
	const url =
		normalizeHttpUrl(
			readString(database, [
				"url",
				"public_url",
				"publicUrl",
				"web_url",
				"webUrl",
				"database_url",
				"databaseUrl",
				"href",
				"link",
			]),
		) ?? buildNotionPageUrlFromId(databaseId);

	const title =
		readString(database, ["database_title", "databaseTitle", "name", "title"]) ??
		extractNotionRichText(database.title) ??
		"Untitled database";

	const description =
		readString(database, ["description", "summary", "snippet"]) ??
		extractNotionRichText(database.description);

	const icon =
		readString(database, ["emoji", "iconEmoji"]) ??
		readNestedString(database, ["icon", "emoji"]);

	const lastEdited = readString(database, [
		"last_edited_time",
		"lastEditedTime",
		"updated_at",
		"updatedAt",
	]);

	const properties: NotionDatabaseProperty[] = isRecord(database.properties)
		? Object.entries(database.properties).map(([key, value]) => {
				const recordValue = isRecord(value) ? value : {};
				return {
					name: readString(recordValue, ["name"]) ?? key,
					type: readString(recordValue, ["type"]) ?? "unknown",
				};
			})
		: [];

	return {
		title,
		url,
		description,
		lastEdited,
		databaseId,
		parentLabel: extractParentLabel(database.parent),
		icon,
		properties,
	};
};

const formatDateLabel = (value: string | undefined): string | undefined => {
	if (!value) {
		return undefined;
	}

	const parsed = new Date(value);
	if (Number.isNaN(parsed.getTime())) {
		return undefined;
	}

	return parsed.toLocaleString();
};

const getCompactPageId = (pageId: string | undefined): string | undefined => {
	if (!pageId) {
		return undefined;
	}

	const normalized = pageId.replace(/-/g, "");
	if (normalized.length <= 10) {
		return normalized;
	}

	return `${normalized.slice(0, 8)}...${normalized.slice(-4)}`;
};

const GenericToolWidget = ({
	toolPart,
	toolName,
	serverName,
	className,
}: HostToolWidgetProps) => (
	<Card
		className={cn(
			"mt-2 w-full gap-3 border-dashed bg-card/60 py-3 shadow-none",
			className,
		)}
	>
		<CardHeader className="px-4">
			<div className="flex items-center justify-between gap-2">
				<div className="flex min-w-0 items-center gap-2">
					<div className="flex size-7 shrink-0 items-center justify-center rounded-md border bg-muted">
						<AppWindowIcon className="size-3.5" />
					</div>
					<div className="min-w-0">
						<CardTitle className="truncate text-sm">Host Widget Preview</CardTitle>
						<CardDescription className="text-xs">
							Hard-coded host interception (prototype)
						</CardDescription>
					</div>
				</div>
				<Badge
					variant="outline"
					className={cn("shrink-0 border", getBadgeClassName(toolPart.state))}
				>
					{getStateLabel(toolPart.state)}
				</Badge>
			</div>
		</CardHeader>
		<CardContent className="grid gap-2 px-4 text-xs">
			<div className="flex flex-wrap items-center gap-2 text-muted-foreground">
				<ServerIcon className="size-3.5" />
				<span className="font-medium text-foreground">{serverName}</span>
				<WrenchIcon className="size-3.5" />
				<span className="font-medium text-foreground">{toolName}</span>
			</div>
			<div className="rounded-md border bg-background/70 p-2">
				<div className="mb-1 flex items-center gap-1.5 text-muted-foreground">
					<BracesIcon className="size-3.5" />
					<span>Input</span>
				</div>
				<p className="break-words leading-relaxed">
					{summarizePayload(toolPart.input)}
				</p>
			</div>
			<div className="rounded-md border bg-background/70 p-2">
				<div className="mb-1 flex items-center gap-1.5 text-muted-foreground">
					<CircleDashedIcon className="size-3.5" />
					<span>Output</span>
				</div>
				<p className="break-words leading-relaxed">{getOutputSummary(toolPart)}</p>
			</div>
		</CardContent>
	</Card>
);

const NotionSearchWidget = ({
	toolPart,
	toolName,
	serverName,
	className,
}: HostToolWidgetProps) => {
	const notionPage = extractNotionPageInfo(toolPart.output);
	const lastEdited = formatDateLabel(notionPage?.lastEdited);
	const compactPageId = getCompactPageId(notionPage?.pageId);

	return (
		<Card
			className={cn(
				"mt-2 w-full gap-3 border-blue-200 bg-blue-50/40 py-3 shadow-none dark:border-blue-500/30 dark:bg-blue-500/5",
				className,
			)}
		>
			<CardHeader className="px-4">
				<div className="flex items-center justify-between gap-2">
					<div className="flex min-w-0 items-center gap-2">
						<div className="flex size-7 shrink-0 items-center justify-center rounded-md border border-blue-200 bg-blue-100 text-blue-700 dark:border-blue-500/30 dark:bg-blue-500/20 dark:text-blue-200">
							<FileSearchIcon className="size-3.5" />
						</div>
						<div className="min-w-0">
							<CardTitle className="truncate text-sm">Notion Page Result</CardTitle>
							<CardDescription className="text-xs">
								Host widget for hard-coded tool: `{toolName}`
							</CardDescription>
						</div>
					</div>
					<Badge
						variant="outline"
						className={cn("shrink-0 border", getBadgeClassName(toolPart.state))}
					>
						{getStateLabel(toolPart.state)}
					</Badge>
				</div>
			</CardHeader>

			<CardContent className="grid gap-3 px-4 text-xs">
				<div className="flex flex-wrap items-center gap-2 text-muted-foreground">
					<ServerIcon className="size-3.5" />
					<span className="font-medium text-foreground">{serverName}</span>
					<WrenchIcon className="size-3.5" />
					<span className="font-medium text-foreground">{toolName}</span>
				</div>

				{notionPage ? (
					<>
						<div className="rounded-md border bg-background/80 p-3">
							<div className="flex items-start gap-2">
								<div className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md border bg-muted text-[11px]">
									{notionPage.icon ?? "N"}
								</div>
								<div className="min-w-0 space-y-1">
									<p className="truncate font-semibold text-sm">{notionPage.title}</p>
									{notionPage.summary && (
										<p className="text-muted-foreground leading-relaxed">
											{truncate(notionPage.summary)}
										</p>
									)}
								</div>
							</div>
						</div>

						<div className="flex flex-wrap items-center gap-3 text-muted-foreground">
							{compactPageId && (
								<span className="font-mono text-[11px]">Page ID: {compactPageId}</span>
							)}
							{lastEdited && (
								<span className="inline-flex items-center gap-1">
									<Clock3Icon className="size-3.5" />
									Updated {lastEdited}
								</span>
							)}
						</div>

						{notionPage.url ? (
							<div>
								<Button asChild size="sm" className="cursor-pointer">
									<a
										href={notionPage.url}
										rel="noopener noreferrer"
										target="_blank"
									>
										Open in Notion
										<ExternalLinkIcon className="size-3.5" />
									</a>
								</Button>
							</div>
						) : (
							<p className="text-muted-foreground">
								Page URL not found in tool output.
							</p>
						)}
					</>
				) : (
					<div className="rounded-md border bg-background/80 p-3">
						<p className="text-muted-foreground leading-relaxed">
							{getOutputSummary(toolPart)}
						</p>
					</div>
				)}
			</CardContent>
		</Card>
	);
};

const NotionCreateDatabaseWidget = ({
	toolPart,
	toolName,
	serverName,
	className,
}: HostToolWidgetProps) => {
	const database = extractNotionDatabaseInfo(toolPart.output);
	const lastEdited = formatDateLabel(database?.lastEdited);
	const compactDatabaseId = getCompactPageId(database?.databaseId);
	const visibleProperties = database?.properties.slice(0, 6) ?? [];
	const hiddenPropertiesCount = Math.max((database?.properties.length ?? 0) - 6, 0);
	const tableColumns =
		visibleProperties.length > 0
			? visibleProperties
			: [{ name: "Name", type: "title" }];
	const previewRowIndexes = [0, 1, 2];

	return (
		<Card
			className={cn(
				"mt-2 w-full gap-3 border-emerald-200 bg-emerald-50/40 py-3 shadow-none dark:border-emerald-500/30 dark:bg-emerald-500/5",
				className,
			)}
		>
			<CardHeader className="px-4">
				<div className="flex items-center justify-between gap-2">
					<div className="flex min-w-0 items-center gap-2">
						<div className="flex size-7 shrink-0 items-center justify-center rounded-md border border-emerald-200 bg-emerald-100 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/20 dark:text-emerald-200">
							<DatabaseIcon className="size-3.5" />
						</div>
						<div className="min-w-0">
							<CardTitle className="truncate text-sm">Notion Database Created</CardTitle>
							<CardDescription className="text-xs">
								Host widget for hard-coded tool: `{toolName}`
							</CardDescription>
						</div>
					</div>
					<Badge
						variant="outline"
						className={cn("shrink-0 border", getBadgeClassName(toolPart.state))}
					>
						{getStateLabel(toolPart.state)}
					</Badge>
				</div>
			</CardHeader>

			<CardContent className="grid gap-3 px-4 text-xs">
				<div className="flex flex-wrap items-center gap-2 text-muted-foreground">
					<ServerIcon className="size-3.5" />
					<span className="font-medium text-foreground">{serverName}</span>
					<WrenchIcon className="size-3.5" />
					<span className="font-medium text-foreground">{toolName}</span>
				</div>

				{database ? (
					<>
						<div className="rounded-md border bg-background/80 p-3">
							<div className="flex items-start gap-2">
								<div className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md border bg-muted text-[11px]">
									{database.icon ?? "DB"}
								</div>
								<div className="min-w-0 space-y-1">
									<div className="flex flex-wrap items-center gap-2">
										<p className="truncate font-semibold text-sm">{database.title}</p>
										<Badge variant="secondary" className="text-[10px]">
											{database.properties.length} fields
										</Badge>
									</div>
									{database.description && (
										<p className="text-muted-foreground leading-relaxed">
											{truncate(database.description)}
										</p>
									)}
								</div>
							</div>
						</div>

						<div className="flex flex-wrap items-center gap-3 text-muted-foreground">
							{compactDatabaseId && (
								<span className="font-mono text-[11px]">
									Database ID: {compactDatabaseId}
								</span>
							)}
							{lastEdited && (
								<span className="inline-flex items-center gap-1">
									<Clock3Icon className="size-3.5" />
									Updated {lastEdited}
								</span>
							)}
							{database.parentLabel && <span>{database.parentLabel}</span>}
						</div>

						<div className="overflow-hidden rounded-lg border border-stone-300/70 bg-white text-[11px] shadow-sm dark:border-zinc-700 dark:bg-zinc-900">
							<div className="flex items-center gap-2 border-b border-stone-200 bg-stone-50 px-3 py-2 text-stone-600 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
								<span className="inline-flex items-center rounded-md border border-stone-200 bg-white px-2 py-0.5 font-medium dark:border-zinc-700 dark:bg-zinc-900">
									Table
								</span>
								<span className="truncate text-stone-500 dark:text-zinc-400">
									{database.title}
								</span>
								<span className="ml-auto inline-flex items-center gap-1 text-stone-500 dark:text-zinc-400">
									<SearchIcon className="size-3" />
									Search
								</span>
							</div>

							<div className="overflow-x-auto">
								<table className="min-w-[620px] w-full border-collapse">
									<thead className="bg-stone-50/70 dark:bg-zinc-800/80">
										<tr>
											{tableColumns.map((property, index) => (
												<th
													key={`${property.name}-${property.type}`}
													className="border-b border-r border-stone-200 px-2 py-1.5 text-left font-medium text-stone-700 dark:border-zinc-700 dark:text-zinc-300"
												>
													<div className="min-w-0">
														<p className="truncate">{property.name}</p>
														<p className="truncate text-[10px] font-normal text-stone-500 dark:text-zinc-500">
															{formatPropertyTypeLabel(
																index === 0 ? "title" : property.type,
															)}
														</p>
													</div>
												</th>
											))}
											<th className="w-8 border-b border-stone-200 px-1 dark:border-zinc-700">
												<PlusIcon className="mx-auto size-3 text-stone-500 dark:text-zinc-400" />
											</th>
										</tr>
									</thead>
									<tbody>
										{previewRowIndexes.map((rowIndex) => (
											<tr
												key={`preview-row-${rowIndex}`}
												className="odd:bg-white even:bg-stone-50/40 dark:odd:bg-zinc-900 dark:even:bg-zinc-900/70"
											>
												{tableColumns.map((property, columnIndex) => (
													<td
														key={`${property.name}-${rowIndex}`}
														className="border-b border-r border-stone-200 px-2 py-2 align-middle dark:border-zinc-700"
													>
														{columnIndex === 0 ? (
															<p className="truncate font-medium text-stone-800 dark:text-zinc-100">
																{getPropertyPreviewValue("title", rowIndex, true)}
															</p>
														) : (
															<p className="truncate text-stone-500 dark:text-zinc-400">
																{getPropertyPreviewValue(
																	property.type,
																	rowIndex,
																	false,
																)}
															</p>
														)}
													</td>
												))}
												<td className="border-b border-stone-200 px-1 dark:border-zinc-700" />
											</tr>
										))}
									</tbody>
								</table>
							</div>

							<div className="flex items-center justify-between border-t border-stone-200 bg-stone-50/80 px-3 py-2 text-stone-600 dark:border-zinc-700 dark:bg-zinc-800/70 dark:text-zinc-300">
								<span>+ New</span>
								<span>{database.properties.length} properties</span>
							</div>
						</div>

						{hiddenPropertiesCount > 0 && (
							<div className="rounded-md border bg-background/80 p-2">
								<p className="text-muted-foreground">
									+{hiddenPropertiesCount} additional properties not shown in this
									preview
								</p>
							</div>
						)}

						{database.url ? (
							<div>
								<Button asChild size="sm" className="cursor-pointer">
									<a
										href={database.url}
										rel="noopener noreferrer"
										target="_blank"
									>
										Open Database in Notion
										<ExternalLinkIcon className="size-3.5" />
									</a>
								</Button>
							</div>
						) : (
							<p className="text-muted-foreground">
								Database URL not found in tool output.
							</p>
						)}
					</>
				) : (
					<div className="rounded-md border bg-background/80 p-3">
						<p className="text-muted-foreground leading-relaxed">
							{getOutputSummary(toolPart)}
						</p>
					</div>
				)}
			</CardContent>
		</Card>
	);
};

export const HostToolWidget = (props: HostToolWidgetProps) => {
	// Host-level hardcoded widget routing.
	switch (props.toolName) {
		case "notion-search":
		case "notion_search":
			return <NotionSearchWidget {...props} />;
		case "notion-create-database":
		case "notion_create_database":
		case "create-database":
		case "create_database":
			return <NotionCreateDatabaseWidget {...props} />;
		default:
			return <GenericToolWidget {...props} />;
	}
};
