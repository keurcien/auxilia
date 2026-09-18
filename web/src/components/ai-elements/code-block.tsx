"use client";

import { cn } from "@/lib/utils";
import { type HTMLAttributes, useEffect, useState } from "react";
import {
	type BundledLanguage,
	codeToHtml,
	type ShikiTransformer,
	type SpecialLanguage,
	type ThemeRegistrationRaw,
} from "shiki";

type CodeBlockProps = HTMLAttributes<HTMLDivElement> & {
	code: string;
	/** `plaintext` renders unhighlighted — for a file whose grammar we don't know. */
	language: BundledLanguage | SpecialLanguage;
	showLineNumbers?: boolean;
	/**
	 * One theme for both colour schemes, for a surface that is dark either
	 * way (the Petrol Mono panel). Given one, the block highlights once
	 * instead of twice and leaves the text colour to the theme; left out, it
	 * keeps the light-plus / dark-plus pair that follows the app theme.
	 */
	theme?: ThemeRegistrationRaw;
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
	language: BundledLanguage | SpecialLanguage,
	showLineNumbers = false,
	theme?: ThemeRegistrationRaw,
) {
	const transformers: ShikiTransformer[] = showLineNumbers
		? [lineNumberTransformer]
		: [];

	if (theme) {
		const html = await codeToHtml(code, { lang: language, theme, transformers });
		return [html, html];
	}

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
	theme,
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

		highlightCode(code, language, showLineNumbers, theme).then(([light, dark]) => {
			if (isMounted) {
				setHtml(light);
				setDarkHtml(dark);
			}
		});

		return () => {
			isMounted = false;
		};
	}, [code, language, shouldHighlight, showLineNumbers, theme]);

	// A theme paints its own foreground; forcing `text-foreground` over it
	// would repaint the plain-text fallback in the app's colour, which on a
	// dark panel is unreadable.
	const preClass = cn(
		"min-w-0 max-w-full overflow-x-auto [&>pre]:m-0 [&>pre]:bg-transparent! [&>pre]:px-3 [&>pre]:py-2.5 [&>pre]:text-[11.5px] [&>pre]:leading-[1.7] [&_code]:font-mono [&_code]:text-[11.5px]",
		!theme && "[&>pre]:text-foreground!",
	);

	return (
		<div
			className={cn(
				"group relative min-w-0 w-full max-w-full overflow-hidden rounded-[6px]",
				!theme && "text-foreground",
				className,
			)}
			{...props}
		>
			<div className="relative min-w-0 max-w-full">
				{!shouldHighlight || !html ? (
					<div className={preClass}>
						<pre>
							<code>{code}</code>
						</pre>
					</div>
				) : theme ? (
					<div
						className={preClass}
						// biome-ignore lint/security/noDangerouslySetInnerHtml: "this is needed."
						dangerouslySetInnerHTML={{ __html: html }}
					/>
				) : (
					<>
						<div
							className={cn(preClass, "dark:hidden")}
							// biome-ignore lint/security/noDangerouslySetInnerHtml: "this is needed."
							dangerouslySetInnerHTML={{ __html: html }}
						/>
						<div
							className={cn(preClass, "hidden dark:block")}
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
