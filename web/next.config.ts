import type { NextConfig } from "next";

const nextConfig: NextConfig = {
	reactCompiler: true,
	output: "standalone",
	images: {
		remotePatterns: [
			{
				protocol: "https",
				hostname: "storage.googleapis.com",
			},
		],
	},
	async redirects() {
		return [
			{
				source: "/",
				destination: "/agents",
				permanent: process.env.NODE_ENV === "production",
			},
		];
	},
};

export default nextConfig;
