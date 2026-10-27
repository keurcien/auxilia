import type { NextConfig } from "next";

const nextConfig: NextConfig = {
	reactCompiler: true,
	output: "standalone",
	// The demo recording builds into its own dist dir (npm run demo:web) so
	// `next build` never clobbers the `.next` of a running `next dev`.
	distDir: process.env.NEXT_DIST_DIR ?? ".next",
	images: {
		remotePatterns: [
			{
				protocol: "https",
				hostname: "pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev",
			},
		],
	},
	async headers() {
		return [
			{
				// Never framed: an HTML artifact's links would otherwise load the
				// signed-in app inside its viewer. The MCP-apps host page and the
				// blank page it writes the app into are the ones the app frames
				// itself.
				source: "/((?!(?:sandbox|mcp-app-frame)\\.html$).*)",
				headers: [
					{ key: "X-Frame-Options", value: "DENY" },
					{ key: "Content-Security-Policy", value: "frame-ancestors 'none'" },
				],
			},
			// They run their parent's HTML same-origin: only the app may frame them.
			...["/sandbox.html", "/mcp-app-frame.html"].map((source) => ({
				source,
				headers: [
					{ key: "X-Frame-Options", value: "SAMEORIGIN" },
					{ key: "Content-Security-Policy", value: "frame-ancestors 'self'" },
				],
			})),
		];
	},
	async redirects() {
		return [
			{
				source: "/",
				destination: "/agents",
				permanent: true,
			},
		];
	},
};

export default nextConfig;
