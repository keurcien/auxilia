import type { Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

/**
 * Screenshot helper for the docs site. Writes PNGs into
 * docs/public/screenshots/ so MDX pages can embed them as
 * ![...](/screenshots/<name>.png).
 *
 * Override the target directory with DOCS_SCREENSHOT_DIR.
 */
const SCREENSHOT_DIR =
	process.env.DOCS_SCREENSHOT_DIR ??
	path.resolve(process.cwd(), "..", "docs", "public", "screenshots");

export interface DocShotOptions {
	/** Capture the full scrollable page instead of the viewport. */
	fullPage?: boolean;
	/** Extra settle time (ms) before capturing — fonts, icons, transitions. */
	settle?: number;
}

export async function docShot(
	page: Page,
	name: string,
	{ fullPage = false, settle = 600 }: DocShotOptions = {},
): Promise<string> {
	await page.waitForLoadState("networkidle").catch(() => {});
	await page.waitForTimeout(settle);
	fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
	const file = path.join(SCREENSHOT_DIR, `${name}.png`);
	await page.screenshot({ path: file, fullPage, animations: "disabled" });
	console.log(`  ✔ ${path.relative(process.cwd(), file)}`);
	return file;
}
