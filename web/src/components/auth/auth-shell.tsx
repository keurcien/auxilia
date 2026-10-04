import { version } from "../../../package.json";
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
	return (
		<div className={`flex ${wide ? "h-svh overflow-hidden" : "min-h-full"}`}>
			{/* Left: form */}
			<div
				className={`flex min-w-0 flex-1 flex-col py-10 ${
					wide ? "h-svh overflow-y-auto" : ""
				}`}
			>
				<div className="flex items-center gap-2.5 px-8 lg:px-14">
					{/* eslint-disable-next-line @next/next/no-img-element -- local SVG, next/image blocks SVG sources */}
					<img src="/logo.svg" alt="auxilia" width={25} height={25} />
					<span className="font-display text-xl font-bold tracking-[-0.02em]">
						auxilia
					</span>
					<span className="ml-1 rounded-sm bg-petrol-chip px-1.5 py-0.5 font-mono text-[11px] text-petrol">
						v{version}
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
				<div className="flex items-center justify-between px-8 text-[11px] text-meta lg:px-14">
					<span>self-hosted</span>
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
				<div className="relative text-xs font-medium text-panel-terminal">
					{"// AGENTS THAT WORK LIKE YOUR TEAM"}
				</div>
				<ProductShowcase />
			</div>
		</div>
	);
}
