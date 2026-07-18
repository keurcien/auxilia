import type { NextConfig } from "next";

const nextConfig: NextConfig = {
	reactCompiler: true,
	output: "standalone",
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
