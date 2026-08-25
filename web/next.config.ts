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
