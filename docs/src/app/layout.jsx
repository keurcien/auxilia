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
						fontFamily: "'Plus Jakarta Sans', sans-serif",
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
					dark: "#141c19",
				}}
				color={{
					hue: 154,
					saturation: 38,
					lightness: { light: 48, dark: 55 },
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
								fontSize: "0.875rem",
							}}
						>
							<span>
								AGPL-3.0 {new Date().getFullYear()} © auxilia — open-source web
								MCP client
							</span>
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
