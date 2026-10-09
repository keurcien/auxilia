"use client";

import { appearanceLogoUrl } from "@/lib/api/resources/appearance";
import { useAppearanceStore } from "@/stores/appearance-store";
import { ProductShowcase } from "./showcase";

/**
 * Shared marketing-style auth layout (design 9a): branded form column on the
 * left, dark product-showcase panel on the right. Used by /auth and /setup.
 */
export function AuthShell({
	title,
	description,
	footer,
	wide = false,
	children,
}: {
	title: string;
	description: string;
	footer?: React.ReactNode;
	wide?: boolean;
	children: React.ReactNode;
}) {
	const appearance = useAppearanceStore((state) => state.appearance);

	return (
		<div className={`flex ${wide ? "h-svh overflow-hidden" : "min-h-full"}`}>
			{/* Left: form */}
			<div
				className={`flex min-w-0 flex-1 flex-col py-10 ${
					wide ? "h-svh overflow-y-auto" : ""
				}`}
			>
				<div className="flex items-center gap-2.5 px-8 lg:px-14">
					{appearance.logoRevision ? (
						// Browser-direct request avoids routing the custom logo through Next's optimizer.
						// eslint-disable-next-line @next/next/no-img-element
						<img
							src={appearanceLogoUrl(appearance.logoRevision)}
							alt=""
							className="size-[25px] rounded-[6px] object-cover"
						/>
					) : (
						<span aria-hidden="true" className="relative size-[25px] shrink-0">
							{/* eslint-disable-next-line @next/next/no-img-element -- local SVG */}
							<img
								src="/logo.svg"
								alt=""
								className="size-[25px] dark:hidden"
							/>
							{/* eslint-disable-next-line @next/next/no-img-element -- local SVG */}
							<img
								src="/logo-dark.svg"
								alt=""
								className="hidden size-[25px] dark:block"
							/>
						</span>
					)}
					<span className="font-display text-xl font-bold tracking-[-0.02em]">
						{appearance.appName}
					</span>
				</div>
				<div
					className={`mx-auto flex w-full flex-1 flex-col px-8 ${
						wide ? "max-w-[760px]" : "max-w-[420px]"
					} ${wide ? "justify-start py-10" : "justify-center"}`}
				>
					<h1 className="font-display text-[40px] font-bold leading-[1.05] tracking-[-0.035em]">
						{title}
					</h1>
					<p className="mt-3.5 text-[15px] leading-[1.6] text-body">
						{description}
					</p>

					<div className="mt-9 flex flex-col gap-4">{children}</div>

					{footer && <p className="mt-7 text-[13.5px] text-label">{footer}</p>}
				</div>
				<div className="flex items-center justify-end px-8 text-[11px] text-meta lg:px-14">
					<span>AGPL-3.0</span>
				</div>
			</div>

			{/* Right: dark showcase panel */}
			<div
				className={`relative hidden w-[46%] flex-none flex-col justify-center gap-6 overflow-hidden bg-panel px-14 py-16 lg:flex ${
					wide ? "h-svh" : ""
				}`}
			>
				<div
					className="absolute inset-0"
					style={{
						backgroundImage:
							"linear-gradient(var(--pm-panel-grid) 1px, transparent 1px), linear-gradient(90deg, var(--pm-panel-grid) 1px, transparent 1px)",
						backgroundSize: "40px 40px",
					}}
				/>
				<div className="relative text-xs font-medium tracking-normal text-panel-terminal">
					Agents that work like your team
				</div>
				<ProductShowcase />
			</div>
		</div>
	);
}
