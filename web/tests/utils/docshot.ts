import { test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

/**
 * Screenshot helper for the docs site. Writes PNGs into
 * docs/public/screenshots/ so MDX pages can embed them as
 * ![...](/screenshots/<name>.png).
 *
 * Override the target directory with DOCS_SCREENSHOT_DIR.
 */
function screenshotDir(): string {
	if (process.env.DOCS_SCREENSHOT_DIR) return process.env.DOCS_SCREENSHOT_DIR;
	// Anchor on the Playwright config (web/playwright.config.ts) instead of
	// process.cwd(), so the target is right no matter where the runner is
	// launched from (repo root, web/, CI…).
	const configFile = test.info().config.configFile;
	const webDir = configFile ? path.dirname(configFile) : process.cwd();
	return path.resolve(webDir, "..", "docs", "public", "screenshots");
}

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
	const dir = screenshotDir();
	fs.mkdirSync(dir, { recursive: true });
	const file = path.join(dir, `${name}.png`);
	await page.screenshot({ path: file, fullPage, animations: "disabled" });
	console.log(`  ✔ ${path.relative(process.cwd(), file)}`);
	return file;
}
