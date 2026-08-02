import type { Metadata } from "next";
import { Hanken_Grotesk, IBM_Plex_Mono, Space_Grotesk } from "next/font/google";
import { ThemeProvider } from "next-themes";
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
};

export default function RootLayout({
	children,
}: Readonly<{
	children: React.ReactNode;
}>) {
	return (
		<html lang="en" className="h-full" suppressHydrationWarning>
			<body
				className={`${spaceGrotesk.variable} ${hankenGrotesk.variable} ${ibmPlexMono.variable} antialiased h-full`}
			>
				<ThemeProvider
					attribute="class"
					defaultTheme="system"
					enableSystem
					disableTransitionOnChange
				>
					{children}
				</ThemeProvider>
			</body>
		</html>
	);
}
