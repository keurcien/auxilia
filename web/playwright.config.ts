import { defineConfig, devices } from "@playwright/test";

const port = process.env.PORT ?? "3000";
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? `http://127.0.0.1:${port}`;
// The demo/docs projects target a production build (`npm run demo:web` →
// next build + next start on :${DEMO_PORT:-3100}) so recordings have no
// dev-tools overlay and no on-demand page compiles. The npm scripts set
// PLAYWRIGHT_BASE_URL accordingly — and the projects only register when it
// is set, so a bare `playwright test` runs just the self-contained `visual`
// project instead of also selecting suites that need the live demo stack.
const demoPort = process.env.DEMO_PORT ?? "3100";
const demoStackBaseURL = process.env.PLAYWRIGHT_BASE_URL ?? `http://localhost:${demoPort}`;
const demoStackConfigured = Boolean(process.env.PLAYWRIGHT_BASE_URL);

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
		// Demo walkthrough recorded as a video, and docs screenshots — both
		// need a running backend, a production frontend (npm run demo:web) and
		// seeded data (demo:seed), so they register only when the npm scripts
		// (or the caller) set PLAYWRIGHT_BASE_URL.
		...(demoStackConfigured
			? [
					{
						name: "demo",
						testMatch: "**/*.demo.spec.ts",
						// Five live agent runs (chat, HITL, sandbox, trigger preview,
						// HTTP invoke) — a slow take has measured ~17 min wall, so give
						// real headroom: the timeout only catches a wedged run.
						timeout: 1_800_000,
						retries: 0,
						// Remote MCP servers answer on their own schedule.
						expect: { timeout: 30_000 },
						use: {
							...devices["Desktop Chrome"],
							baseURL: demoStackBaseURL,
							viewport: { width: 1440, height: 900 },
							video: {
								mode: "on" as const,
								size: { width: 1440, height: 900 },
							},
							trace: "off" as const,
						},
					},
					{
						name: "docs",
						testMatch: "**/*.docs.spec.ts",
						timeout: 120_000,
						retries: 0,
						// Remote MCP servers answer on their own schedule.
						expect: { timeout: 30_000 },
						use: {
							...devices["Desktop Chrome"],
							baseURL: demoStackBaseURL,
							viewport: { width: 1440, height: 900 },
							video: "off" as const,
							trace: "off" as const,
						},
					},
				]
			: []),
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
