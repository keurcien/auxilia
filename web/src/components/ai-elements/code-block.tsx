"use client";

import { cn } from "@/lib/utils";
import { type HTMLAttributes, useEffect, useState } from "react";
import { type BundledLanguage, codeToHtml, type ShikiTransformer } from "shiki";

type CodeBlockProps = HTMLAttributes<HTMLDivElement> & {
	code: string;
	language: BundledLanguage;
	showLineNumbers?: boolean;
};

const lineNumberTransformer: ShikiTransformer = {
	name: "line-numbers",
	line(node, line) {
		node.children.unshift({
			type: "element",
			tagName: "span",
			properties: {
				className: [
					"inline-block",
					"min-w-10",
					"mr-4",
					"text-right",
					"select-none",
					"text-muted-foreground",
				],
			},
			children: [{ type: "text", value: String(line) }],
		});
	},
};

async function highlightCode(
	code: string,
	language: BundledLanguage,
	showLineNumbers = false,
) {
	const transformers: ShikiTransformer[] = showLineNumbers
		? [lineNumberTransformer]
		: [];

	return await Promise.all([
		codeToHtml(code, {
			lang: language,
			theme: "light-plus",
			transformers,
		}),
		codeToHtml(code, {
			lang: language,
			theme: "dark-plus",
			transformers,
		}),
	]);
}

// Above this size, Shiki's regex tokenizer + the resulting highlighted DOM
// freeze the main thread and bog down scrolling. Stay on the plain <pre>
// fallback for these — indentation is preserved, only syntax colors are lost.
export const SHIKI_MAX_CHARS = 30_000;

export const CodeBlock = ({
	code,
	language,
	showLineNumbers = false,
	className,
	children,
	...props
}: CodeBlockProps) => {
	const [html, setHtml] = useState<string>("");
	const [darkHtml, setDarkHtml] = useState<string>("");
	const shouldHighlight = code.length <= SHIKI_MAX_CHARS;

	useEffect(() => {
		if (!shouldHighlight) {
			return;
		}

		let isMounted = true;

		highlightCode(code, language, showLineNumbers).then(([light, dark]) => {
			if (isMounted) {
				setHtml(light);
				setDarkHtml(dark);
			}
		});

		return () => {
			isMounted = false;
		};
	}, [code, language, shouldHighlight, showLineNumbers]);

	return (
		<div
			className={cn(
				"group relative min-w-0 w-full max-w-full overflow-hidden rounded-md border border-border/30 text-foreground",
				className,
			)}
			{...props}
		>
			<div className="relative min-w-0 max-w-full">
				{!shouldHighlight || !html ? (
					<div className="min-w-0 max-w-full overflow-x-auto bg-background [&>pre]:m-0 [&>pre]:bg-background! [&>pre]:p-4 [&>pre]:text-foreground! [&>pre]:text-sm [&_code]:font-mono [&_code]:text-sm">
						<pre>
							<code>{code}</code>
						</pre>
					</div>
				) : (
					<>
						<div
							className="min-w-0 max-w-full overflow-x-auto bg-background dark:hidden [&>pre]:m-0 [&>pre]:bg-background! [&>pre]:p-4 [&>pre]:text-foreground! [&>pre]:text-sm [&_code]:font-mono [&_code]:text-sm"
							// biome-ignore lint/security/noDangerouslySetInnerHtml: "this is needed."
							dangerouslySetInnerHTML={{ __html: html }}
						/>
						<div
							className="hidden min-w-0 max-w-full overflow-x-auto bg-background dark:block [&>pre]:m-0 [&>pre]:bg-background! [&>pre]:p-4 [&>pre]:text-foreground! [&>pre]:text-sm [&_code]:font-mono [&_code]:text-sm"
							// biome-ignore lint/security/noDangerouslySetInnerHtml: "this is needed."
							dangerouslySetInnerHTML={{ __html: darkHtml }}
						/>
					</>
				)}
				{children && (
					<div className="absolute top-2 right-2 flex items-center gap-2">
						{children}
					</div>
				)}
			</div>
		</div>
	);
};
