"use client";

import { useState, useEffect } from "react";

const DEMO_STEPS = 8;
// One extra beat at the end of the loop where everything fades out in place
// (no downward slide) before the cycle restarts.
const DEMO_CYCLE = DEMO_STEPS + 1;
const DEMO_STEP_MS = 1300;

const DEMO_TOOL_LINES = [
	{
		step: 2,
		domain: "metabase.com",
		label: "Run query",
		meta: "· sales by brand",
	},
	{
		step: 3,
		domain: "metabase.com",
		label: "Run query",
		meta: "· forecast vs actual",
	},
	{
		step: 4,
		domain: "slack.com",
		label: "Search messages",
		meta: "· #sales-ops",
	},
];

function Favicon({ domain }: { domain: string }) {
	return (
		// eslint-disable-next-line @next/next/no-img-element -- tiny external favicon, not worth the image pipeline
		<img
			src={`https://www.google.com/s2/favicons?domain=${domain}&sz=64`}
			alt=""
			className="size-[13px]"
		/>
	);
}

/**
 * Generic product showcase looping on the dark panel (design 9a):
 * 8 steps + 1 fade-out beat, ~1.3s each, fade + 8px rise. Everything stays visible under
 * prefers-reduced-motion (motion-reduce variants beat the step classes).
 */
export function ProductShowcase() {
	const [step, setStep] = useState(0);

	useEffect(() => {
		const timer = setInterval(() => {
			setStep((s) => (s + 1) % DEMO_CYCLE);
		}, DEMO_STEP_MS);
		return () => {
			clearInterval(timer);
		};
	}, []);

	const vis = (n: number) => {
		const shown = step >= n && step < DEMO_STEPS;
		// During the fade-out beat, stay at translate-y-0 so elements fade in
		// place instead of sliding down; they snap back below (translate-y-2)
		// only once invisible, ready to rise in again on the next cycle.
		const hidden =
			step === DEMO_STEPS ? "opacity-0 translate-y-0" : "opacity-0 translate-y-2";
		return `transition-[opacity,transform] duration-[450ms] ease-out motion-reduce:transition-none motion-reduce:opacity-100 motion-reduce:translate-y-0 ${
			shown ? "opacity-100 translate-y-0" : hidden
		}`;
	};

	return (
		<div aria-hidden="true" className="relative flex flex-col gap-5">
			<div className="flex flex-col gap-1.5 rounded-xl border border-panel-border-strong bg-panel-card px-5.5 py-5">
				<div
					className={`mb-2 max-w-[85%] self-end rounded-[10px_10px_2px_10px] bg-white/8 px-3.5 py-2.5 text-[13.5px] leading-[1.55] text-panel-button ${vis(0)}`}
				>
					Which brands from the FW26 sale are underperforming?
				</div>
				<div
					className={`flex items-center gap-2 py-1 font-mono text-[10.5px] text-panel-dim ${vis(1)}`}
				>
					<span className="flex size-5 items-center justify-center rounded-[5px] bg-pastel-mint text-[11px]">
						📊
					</span>
					data-analyst is working…
				</div>
				{DEMO_TOOL_LINES.map((line) => (
					<div
						key={`${line.label}-${line.meta}`}
						className={`flex items-center gap-2 py-1.5 font-mono text-[11.5px] text-panel-terminal ${vis(line.step)}`}
					>
						<Favicon domain={line.domain} />
						{line.label}
						<span className="text-panel-dim">{line.meta}</span>
						<span className="ml-auto text-panel-success">ok</span>
					</div>
				))}
				<div
					className={`mt-2 text-[13.5px] leading-[1.6] text-panel-body ${vis(5)}`}
				>
					3 of 24 brands are more than 15% under forecast. Biggest gap:{" "}
					<strong className="text-white">Maison Rive (−31%)</strong> — traffic
					is fine, conversion dropped after the price update.
				</div>
			</div>
			<div
				className={`flex flex-col gap-2 rounded-xl border border-panel-attention/35 bg-panel-card px-5 py-4 ${vis(6)}`}
			>
				<div className="flex items-center gap-2 font-mono text-[10.5px] font-semibold tracking-[0.07em] text-panel-attention">
					⏸ HUMANS STAY IN CONTROL
				</div>
				<div className="text-[13px] leading-[1.6] text-panel-body">
					Sensitive tools wait for approval — in chat or Slack — before
					anything runs.
				</div>
			</div>
			<div className={`flex gap-5 font-mono text-[11.5px] text-panel-dim ${vis(7)}`}>
				<span>
					<span className="text-panel-success">open source</span> ·
					self-hosted
				</span>
				<span className="text-panel-success">any model</span>
				<span>
					<span className="text-panel-success">MCP</span> native
				</span>
			</div>
		</div>
	);
}
