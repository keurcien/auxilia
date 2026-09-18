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

async function highlightToHtml(
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

/**
 * Shiki's rendered output, injected as HTML.
 *
 * One place rather than three, so the reason this is safe is stated once and
 * the suppressions sit on the line the scanners actually report. `html` is
 * always `highlightToHtml`'s return value for `code` — shiki escapes the
 * source it highlights, so nothing from a user or a response body reaches
 * the DOM as markup. Do not call this with anything else.
 */
function ShikiHtml({ className, html }: { className: string; html: string }) {
	const markup = { __html: html };
	// `nosemgrep` trails the statement rather than sitting above it: semgrep
	// honours the match line or the one directly before, and the biome
	// suppression has to occupy the line above.
	// biome-ignore lint/security/noDangerouslySetInnerHtml: shiki's own escaped output
	return <div className={className} dangerouslySetInnerHTML={markup} />; // nosemgrep
}

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

		highlightToHtml(code, language, showLineNumbers, theme)
			.then(([light, dark]) => {
				if (isMounted) {
					setHtml(light);
					setDarkHtml(dark);
				}
			})
			.catch(() => {
				// A grammar shiki cannot load leaves the plain <pre> fallback in
				// place — indentation intact, only the colours missing. Never a
				// blank block, and never an unhandled rejection.
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
		// A themed block sits on the dark panel, so the *fallback* — over
		// SHIKI_MAX_CHARS, or shiki failing — needs the panel's own text
		// colour. Inheriting `foreground` put near-black text on it in light
		// mode, which is the theme's background.
		theme ? "[&>pre]:text-panel-body!" : "[&>pre]:text-foreground!",
	);

	return (
		<div
			className={cn(
				"group relative min-w-0 w-full max-w-full overflow-hidden rounded-[6px]",
				theme ? "text-panel-body" : "text-foreground",
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
					<ShikiHtml className={preClass} html={html} />
				) : (
					<>
						<ShikiHtml className={cn(preClass, "dark:hidden")} html={html} />
						<ShikiHtml
							className={cn(preClass, "hidden dark:block")}
							html={darkHtml}
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
