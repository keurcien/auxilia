import { defineConfig, devices } from "@playwright/test";

const port = process.env.PORT ?? "3000";
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? `http://127.0.0.1:${port}`;
// The demo/docs projects target a production build (`npm run demo:web` →
// next build + next start on :3100) so recordings have no dev-tools overlay
// and no on-demand page compiles. The npm scripts default the URL there.
const demoStackBaseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3100";

export default defineConfig({
	testDir: "./tests",
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
			testMatch: "**/*.visual.spec.ts",
			use: {
				...devices["Desktop Chrome"],
				viewport: { width: 1440, height: 900 },
			},
		},
		// Demo walkthrough recorded as a video. Needs a running backend, a
		// production frontend (npm run demo:web) and seeded data (demo:seed).
		{
			name: "demo",
			testMatch: "**/*.demo.spec.ts",
			// Five live agent runs (chat, HITL, sandbox, trigger preview, HTTP
			// invoke) — a full take has measured ~17 min wall, so give real
			// headroom: the timeout only catches a wedged run.
			timeout: 1_800_000,
			retries: 0,
			// Remote MCP servers answer on their own schedule — allow for it.
			expect: { timeout: 30_000 },
			use: {
				...devices["Desktop Chrome"],
				baseURL: demoStackBaseURL,
				viewport: { width: 1440, height: 900 },
				video: { mode: "on", size: { width: 1440, height: 900 } },
				trace: "off",
			},
		},
		// Docs screenshots written to docs/public/screenshots/. Runs against
		// the same production stack + seeded data as the demo project.
		{
			name: "docs",
			testMatch: "**/*.docs.spec.ts",
			timeout: 120_000,
			retries: 0,
			// Remote MCP servers answer on their own schedule — allow for it.
			expect: { timeout: 30_000 },
			use: {
				...devices["Desktop Chrome"],
				baseURL: demoStackBaseURL,
				viewport: { width: 1440, height: 900 },
				video: "off",
				trace: "off",
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
