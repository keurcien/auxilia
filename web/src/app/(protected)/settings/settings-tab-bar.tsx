"use client";

import Link from "next/link";
import {
	Activity,
	Brain,
	Container,
	Cpu,
	KeyRound,
	Link2,
	LockKeyhole,
	MessageCircle,
	MessagesSquare,
	Palette,
	ShieldCheck,
	SlidersHorizontal,
	UserRound,
	type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface TabDefinition {
	key: string;
	label: string;
	shortLabel?: string;
	icon: LucideIcon;
}

const PROFILE_TABS: TabDefinition[] = [
	{ key: "information", label: "Information", shortLabel: "Info", icon: UserRound },
	{ key: "security", label: "Security", icon: ShieldCheck },
	{ key: "preferences", label: "Preferences", shortLabel: "Options", icon: SlidersHorizontal },
	{ key: "threads", label: "Threads", icon: MessagesSquare },
	{ key: "memories", label: "Memories", icon: Brain },
	{ key: "connected-accounts", label: "Connected accounts", shortLabel: "Accounts", icon: Link2 },
	{ key: "tokens", label: "Access tokens", shortLabel: "Tokens", icon: KeyRound },
];

const ADMIN_TABS: TabDefinition[] = [
	{ key: "models", label: "Models", icon: Cpu },
	{ key: "authentication", label: "Authentication", shortLabel: "Sign-in", icon: LockKeyhole },
	{ key: "messaging", label: "Messaging", icon: MessageCircle },
	{ key: "observability", label: "Observability", shortLabel: "Tracing", icon: Activity },
	{ key: "sandboxes", label: "Sandboxes", icon: Container },
	{ key: "appearance", label: "Appearance", icon: Palette },
];

/** Tabs for the page's current family: every profile section, or the
 * workspace settings tabs, which only admins can reach. */
export function settingsTabBarItems({
	tab,
	profileSection,
	isAdmin,
}: {
	tab: string;
	profileSection: string;
	isAdmin: boolean;
}): SettingsTabBarItem[] {
	if (tab === "profile") {
		return PROFILE_TABS.map(({ key, ...definition }) => ({
			...definition,
			key,
			href: `/settings?tab=profile&section=${key}`,
			active: profileSection === key,
		}));
	}
	if (!isAdmin) return [];
	return ADMIN_TABS.map(({ key, ...definition }) => ({
		...definition,
		key,
		href: `/settings?tab=${key}`,
		active: tab === key,
	}));
}

export interface SettingsTabBarItem {
	key: string;
	/** Full section name, read by screen readers instead of `shortLabel`. */
	label: string;
	/** Compact caption under the icon; defaults to `label`. */
	shortLabel?: string;
	icon: LucideIcon;
	href: string;
	active: boolean;
}

/**
 * Bottom tab bar for the Settings and Profile subpages below `lg`, where the
 * desktop left rail is hidden. It is the last row of the page's flex column
 * rather than a fixed overlay, so the scrolling content always ends above it
 * and it never covers the off-canvas sidebar or any global navigation.
 */
export function SettingsTabBar({
	label,
	items,
}: {
	label: string;
	items: SettingsTabBarItem[];
}) {
	if (items.length === 0) return null;
	return (
		<nav
			aria-label={label}
			data-settings-tab-bar=""
			className="shrink-0 border-t border-border bg-background pb-[env(safe-area-inset-bottom)] lg:hidden"
		>
			<ul
				className="grid"
				style={{
					gridTemplateColumns: `repeat(${items.length}, minmax(0, 1fr))`,
				}}
			>
				{items.map(({ key, label: itemLabel, shortLabel, icon: Icon, href, active }) => (
					<li key={key} className="min-w-0">
						<Link
							href={href}
							replace
							scroll={false}
							aria-current={active ? "page" : undefined}
							className={cn(
								"relative flex min-h-14 w-full flex-col items-center justify-center gap-1 pt-1.5 pb-1 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-petrol/40",
								active
									? "text-petrol dark:text-panel-terminal"
									: "text-meta hover:text-foreground dark:text-panel-dim dark:hover:text-panel-body",
							)}
						>
							<span
								aria-hidden
								className={cn(
									"absolute inset-x-2 top-0 h-0.5 rounded-b-full",
									active ? "bg-petrol dark:bg-panel-terminal" : "bg-transparent",
								)}
							/>
							<span
								aria-hidden
								className={cn(
									"flex h-6 w-10 max-w-full items-center justify-center rounded-full transition-colors",
									active && "bg-petrol-tint dark:bg-white/10",
								)}
							>
								<Icon className="size-[17px]" />
							</span>
							<span
								aria-hidden
								className={cn(
									"line-clamp-2 w-full text-center text-[9px] leading-[1.15] break-words",
									active ? "font-semibold" : "font-medium",
								)}
							>
								{shortLabel ?? itemLabel}
							</span>
							<span className="sr-only">{itemLabel}</span>
						</Link>
					</li>
				))}
			</ul>
		</nav>
	);
}
