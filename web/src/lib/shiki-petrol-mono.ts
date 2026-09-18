import type { ThemeRegistrationRaw } from "shiki";

/**
 * Petrol Mono as a syntax theme — the dark panel the login showcase, the
 * landing terminal and the editor console already use, so code in the app
 * reads as one surface instead of borrowing VS Code's palette.
 *
 * Every colour here is a `--pm-panel-*` token from `globals.css`, kept as a
 * literal because shiki resolves themes before the browser has any CSS: it
 * needs real colours, not `var(...)`. If those tokens move, move these.
 *
 *   panel      #101820  background (`--pm-panel`, the ink)
 *   body       #c9d4d6  plain text  (`--pm-panel-body`)
 *   terminal   #9fd6cb  keywords, types, headings (`--pm-panel-terminal`)
 *   success    #7bc7a9  strings (`--pm-panel-success`)
 *   attention  #e8a085  numbers, constants, attributes (`--pm-panel-attention`)
 *   button     #e6edee  function names — the brightest step (`--pm-panel-button`)
 *   dim        #5a6e74  comments and punctuation (`--pm-panel-dim`)
 *
 * The palette is five hues on purpose. Code here is read, not written, so it
 * is grouped coarsely — what a thing *is* (teal), what it *says* (green),
 * what it *counts* (warm) — rather than split into the twenty scopes a
 * writing theme wants.
 */

const PANEL = "#101820";
const BODY = "#c9d4d6";
const TERMINAL = "#9fd6cb";
const SUCCESS = "#7bc7a9";
const ATTENTION = "#e8a085";
const BUTTON = "#e6edee";
const DIM = "#5a6e74";

export const PETROL_MONO_THEME: ThemeRegistrationRaw = {
	name: "petrol-mono",
	type: "dark",
	colors: {
		"editor.background": PANEL,
		"editor.foreground": BODY,
	},
	settings: [
		{ settings: { background: PANEL, foreground: BODY } },
		{
			scope: ["comment", "punctuation.definition.comment"],
			settings: { foreground: DIM, fontStyle: "italic" },
		},
		{
			scope: [
				"string",
				"string.quoted",
				"constant.other.symbol",
				"punctuation.definition.string",
			],
			settings: { foreground: SUCCESS },
		},
		{
			scope: [
				"constant.numeric",
				"constant.language",
				"constant.character",
				"keyword.other.unit",
				"entity.other.attribute-name",
			],
			settings: { foreground: ATTENTION },
		},
		{
			scope: [
				"keyword",
				"storage",
				"storage.type",
				"storage.modifier",
				"keyword.control",
				"keyword.operator.new",
				"variable.language",
			],
			settings: { foreground: TERMINAL },
		},
		{
			scope: [
				"entity.name.type",
				"entity.name.class",
				"support.type",
				"support.class",
				"entity.name.tag",
			],
			settings: { foreground: TERMINAL },
		},
		{
			scope: ["entity.name.function", "support.function", "meta.function-call"],
			settings: { foreground: BUTTON },
		},
		{
			scope: ["variable", "variable.parameter", "meta.definition.variable"],
			settings: { foreground: BODY },
		},
		{
			scope: ["punctuation", "meta.brace", "keyword.operator"],
			settings: { foreground: DIM },
		},
		// Markdown: a SKILL.md or a reference doc is the common case here.
		{ scope: ["markup.heading", "entity.name.section"], settings: { foreground: TERMINAL, fontStyle: "bold" } },
		{ scope: ["markup.bold"], settings: { fontStyle: "bold" } },
		{ scope: ["markup.italic"], settings: { fontStyle: "italic" } },
		{ scope: ["markup.inline.raw", "markup.fenced_code"], settings: { foreground: SUCCESS } },
		{ scope: ["markup.underline.link", "string.other.link"], settings: { foreground: ATTENTION } },
		{ scope: ["markup.list", "punctuation.definition.list"], settings: { foreground: DIM } },
		{ scope: ["invalid"], settings: { foreground: ATTENTION } },
	],
};
