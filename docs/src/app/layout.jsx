import { Footer, Layout, Navbar, ThemeSwitch } from "nextra-theme-docs";
import { Head } from "nextra/components";
import { getPageMap } from "nextra/page-map";
import "nextra-theme-docs/style.css";
import "./globals.css";

export const metadata = {
	title: {
		template: "%s – auxilia",
		default: "auxilia – Open-Source Web MCP Client",
	},
	description:
		"Host and share MCP-powered AI assistants for your team. Open-source, self-hosted.",
	applicationName: "auxilia",
	icons: {
		icon: "/logo.svg",
	},
	openGraph: {
		images: [
			{
				url: "/logo.svg",
			},
		],
	},
};

export default async function RootLayout({ children }) {
	const navbar = (
		<Navbar
			logo={
				<span
					style={{
						display: "inline-flex",
						alignItems: "center",
						gap: "0.5rem",
						fontFamily: "'Space Grotesk', sans-serif",
						fontWeight: 700,
						fontSize: "1.1rem",
						letterSpacing: "-0.02em",
						color: "var(--auxilia-fg)",
					}}
				>
					<img
						src="/logo.svg"
						alt="auxilia"
						className="logo-light"
						style={{ height: "1.5rem" }}
					/>
					<img
						src="/logo-dark.svg"
						alt="auxilia"
						className="logo-dark"
						style={{ height: "1.5rem" }}
					/>
					auxilia
					<span className="pm-version-chip">v1.x</span>
				</span>
			}
			projectLink="https://github.com/keurcien/auxilia"
		>
			<ThemeSwitch lite />
		</Navbar>
	);
	const pageMap = await getPageMap();
	return (
		<html lang="en" dir="ltr" suppressHydrationWarning>
			<Head
				backgroundColor={{
					light: "#ffffff",
					dark: "#101820",
				}}
				color={{
					hue: { light: 190, dark: 168 },
					saturation: { light: 67, dark: 40 },
					lightness: { light: 26, dark: 73 },
				}}
			/>
			<body>
				<Layout
					navbar={navbar}
					footer={
						<Footer
							style={{
								backgroundColor: "transparent",
								borderTop: "1px solid var(--auxilia-sidebar-border)",
								color: "var(--auxilia-muted)",
								fontFamily: "'IBM Plex Mono', monospace",
								fontSize: "13px",
								display: "flex",
								justifyContent: "space-between",
								flexWrap: "wrap",
								gap: "0.5rem",
							}}
						>
							<span>
								AGPL-3.0 {new Date().getFullYear()} © auxilia · built with
								LangGraph + MCP
							</span>
							<span>github.com/keurcien/auxilia</span>
						</Footer>
					}
					editLink="Edit this page on GitHub"
					docsRepositoryBase="https://github.com/keurcien/auxilia/tree/main/docs"
					sidebar={{ defaultMenuCollapseLevel: 1, toggleButton: false }}
					pageMap={pageMap}
				>
					{children}
				</Layout>
			</body>
		</html>
	);
}
