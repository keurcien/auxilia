"use client";

import { useEffect } from "react";
import { appearanceLogoUrl } from "@/lib/api/resources/appearance";
import { useAppearanceStore } from "@/stores/appearance-store";

export function AppearanceInitializer() {
	const appearance = useAppearanceStore((state) => state.appearance);
	const fetchAppearance = useAppearanceStore((state) => state.fetchAppearance);

	useEffect(() => {
		const retry = () => {
			void fetchAppearance();
		};
		retry();
		window.addEventListener("online", retry);
		window.addEventListener("focus", retry);
		return () => {
			window.removeEventListener("online", retry);
			window.removeEventListener("focus", retry);
		};
	}, [fetchAppearance]);

	useEffect(() => {
		document.title = appearance.appName;

		let favicon = document.querySelector<HTMLLinkElement>(
			'link[data-workspace-favicon="true"]',
		);
		if (!favicon) {
			favicon = document.createElement("link");
			favicon.rel = "icon";
			favicon.dataset.workspaceFavicon = "true";
			document.head.appendChild(favicon);
		}
		favicon.href = appearance.logoRevision
			? appearanceLogoUrl(appearance.logoRevision)
			: "/pwa-icon.svg";
	}, [appearance]);

	return null;
}
