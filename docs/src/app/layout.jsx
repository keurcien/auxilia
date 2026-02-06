import { Footer, Layout, Navbar } from "nextra-theme-docs";
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
		"Host and share MCP-powered AI assistants for your team. Open-source, self-hosted",
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
				<span style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontWeight: 700, fontSize: "1.1rem" }}>
					<img src="/logo.svg" alt="auxilia" className="logo-light" style={{ height: "1.5rem" }} />
					<img src="/logo-dark.svg" alt="auxilia" className="logo-dark" style={{ height: "1.5rem" }} />
					auxilia
				</span>
			}
			projectLink="https://github.com/keurcien/auxilia"
		/>
	);
	const pageMap = await getPageMap();
	return (
		<html lang="en" dir="ltr" suppressHydrationWarning>
			<Head faviconGlyph="◆" />
			<body>
				<Layout
					navbar={navbar}
					footer={
						<Footer>AGPL-3.0 {new Date().getFullYear()} © auxilia.</Footer>
					}
					editLink="Edit this page on GitHub"
					docsRepositoryBase="https://github.com/keurcien/auxilia/tree/main/docs"
					sidebar={{ defaultMenuCollapseLevel: 1 }}
					pageMap={pageMap}
				>
					{children}
				</Layout>
			</body>
		</html>
	);
}
