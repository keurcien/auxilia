import { defineConfig, devices } from "@playwright/test";

const port = process.env.PORT ?? "3000";
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? `http://127.0.0.1:${port}`;

export default defineConfig({
	testDir: "./tests",
	testMatch: "**/*.visual.spec.ts",
	fullyParallel: true,
	forbidOnly: !!process.env.CI,
	retries: process.env.CI ? 2 : 0,
	workers: process.env.CI ? 1 : undefined,
	timeout: 30_000,
	outputDir: "./test-results/playwright",
	reporter: process.env.CI
		? [
				["github"],
				["html", { open: "never" }],
			]
		: [["html", { open: "never" }]],
	expect: {
		timeout: 5_000,
		toHaveScreenshot: {
			animations: "disabled",
			maxDiffPixelRatio: 0.01,
			threshold: 0.2,
		},
	},
	// Keep names OS-neutral; generate committed baselines with the Docker update script.
	snapshotPathTemplate:
		"{testDir}/{testFileDir}/{testFileName}-snapshots/{arg}{-projectName}{ext}",
	use: {
		baseURL,
		locale: "en-US",
		timezoneId: "UTC",
		trace: "on-first-retry",
		screenshot: "only-on-failure",
		video: "retain-on-failure",
	},
	projects: [
		{
			name: "visual",
			use: {
				...devices["Desktop Chrome"],
				viewport: { width: 1440, height: 900 },
			},
		},
	],
	webServer: process.env.PLAYWRIGHT_BASE_URL
		? undefined
		: {
				command: `npm run build && npm run start -- --hostname 127.0.0.1 --port ${port}`,
				url: baseURL,
				reuseExistingServer: !process.env.CI,
				timeout: 180_000,
				stdout: "pipe",
				stderr: "pipe",
			},
});
