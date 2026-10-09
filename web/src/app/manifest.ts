import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
	return {
		name: "auxilia",
		short_name: "auxilia",
		description: "Build and use MCP-powered AI assistants.",
		start_url: "/agents",
		scope: "/",
		display: "standalone",
		background_color: "#ffffff",
		theme_color: "#16606e",
		orientation: "any",
		categories: ["productivity", "utilities"],
		icons: [
			{
				src: "/pwa-icon-192.png",
				sizes: "192x192",
				type: "image/png",
				purpose: "any",
			},
			{
				src: "/pwa-icon-512.png",
				sizes: "512x512",
				type: "image/png",
				purpose: "any",
			},
			{
				src: "/pwa-icon-512.png",
				sizes: "512x512",
				type: "image/png",
				purpose: "maskable",
			},
		],
	};
}
