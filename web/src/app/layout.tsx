import type { Metadata, Viewport } from "next";
import { Hanken_Grotesk, IBM_Plex_Mono, Space_Grotesk } from "next/font/google";
import { ThemeProvider } from "next-themes";
import { AppearanceInitializer } from "@/components/providers/appearance-initializer";
import { DialogProvider } from "@/components/providers/dialog-provider";
import { Toaster } from "@/components/ui/sonner";
import "./globals.css";

// Petrol Mono design system fonts (see design/README.md):
// - Space Grotesk: display only (page H1s, wordmark, landing card titles)
// - Hanken Grotesk: all UI text
// - IBM Plex Mono: eyebrows, field labels, agent names, metadata, code
const spaceGrotesk = Space_Grotesk({
	variable: "--font-space-grotesk",
	subsets: ["latin"],
});

const hankenGrotesk = Hanken_Grotesk({
	variable: "--font-hanken-grotesk",
	subsets: ["latin"],
});

const ibmPlexMono = IBM_Plex_Mono({
	variable: "--font-ibm-plex-mono",
	subsets: ["latin"],
	weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
	title: "auxilia",
	description: "Platform for building AI-powered assistants",
	applicationName: "auxilia",
	icons: {
		apple: [
			{
				url: "/apple-touch-icon.png",
				sizes: "180x180",
				type: "image/png",
			},
		],
	},
	appleWebApp: {
		capable: true,
		title: "auxilia",
		statusBarStyle: "default",
	},
	formatDetection: {
		telephone: false,
	},
};

export const viewport: Viewport = {
	colorScheme: "light dark",
	themeColor: [
		{ media: "(prefers-color-scheme: light)", color: "#16606e" },
		{ media: "(prefers-color-scheme: dark)", color: "#0c1318" },
	],
};

export default function RootLayout({
	children,
}: Readonly<{
	children: React.ReactNode;
}>) {
	return (
		<html lang="en" className="h-full" suppressHydrationWarning>
			<head>
				<link
					rel="icon"
					href="/pwa-icon.svg"
					data-workspace-favicon="true"
				/>
			</head>
			<body
				className={`${spaceGrotesk.variable} ${hankenGrotesk.variable} ${ibmPlexMono.variable} antialiased h-full`}
			>
				<ThemeProvider
					attribute="class"
					defaultTheme="system"
					enableSystem
					disableTransitionOnChange
				>
					<AppearanceInitializer />
					<DialogProvider>{children}</DialogProvider>
					<Toaster />
				</ThemeProvider>
			</body>
		</html>
	);
}
