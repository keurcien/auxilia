// Stricter ESLint config used ONLY by the pre-commit hook (see
// .pre-commit-config.yaml), which lints just the files you change. It layers
// type-aware rules on top of the base config so violations are caught before
// commit — without changing `npm run lint` / `next build`, which keep using
// eslint.config.mjs and stay unaffected by the repo's existing violations.
import base from "./eslint.config.mjs";

export default [
	...base,
	{
		files: ["src/**/*.{ts,tsx}"],
		languageOptions: {
			parserOptions: {
				projectService: true,
				tsconfigRootDir: import.meta.dirname,
			},
		},
		rules: {
			// "Promise-returning function provided to attribute where a void
			// return was expected" — wrap async handlers: onClick={() => { void fn(); }}
			"@typescript-eslint/no-misused-promises": "error",
			// "Returning a void expression from an arrow function shorthand is
			// forbidden" — use a block body: (x) => { doVoidThing(x); }
			"@typescript-eslint/no-confusing-void-expression": "error",
		},
	},
];
