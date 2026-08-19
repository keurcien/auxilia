"use client";

import { useState } from "react";

const CLONE_COMMAND = "git clone https://github.com/keurcien/auxilia && cd auxilia && make up";

function CloneChip() {
	const [copied, setCopied] = useState(false);

	const copy = () => {
		void navigator.clipboard.writeText(CLONE_COMMAND).then(() => {
			setCopied(true);
			setTimeout(() => {
				setCopied(false);
			}, 2000);
		});
	};

	return (
		// Display and clipboard share CLONE_COMMAND — a reader copying the
		// visible text by hand must get the same runnable command.
		<span className="pm-clone-chip">
			<span className="pm-dollar">$</span> {CLONE_COMMAND}
			<button type="button" className="pm-clone-copy" onClick={copy}>
				{copied ? "copied!" : "copy"}
			</button>
		</span>
	);
}

export function LandingHero() {
	return (
		<div className="pm-hero">
			<div className="pm-eyebrow">{"// OPEN-SOURCE MCP CLIENT FOR TEAMS"}</div>
			<h1 className="pm-hero-title">
				Ship agents to your team, not to someone&apos;s laptop.
			</h1>
			<p className="pm-hero-sub">
				Register MCP servers once, define agents with guardrails, and run them
				in the browser, in Slack, or on a schedule — all on infrastructure you
				control.
			</p>
			<div className="pm-cta-row">
				<a href="/get-started" className="pm-btn-ink">
					Get started →
				</a>
				<CloneChip />
			</div>
		</div>
	);
}

const FEATURES = [
	{
		num: "01 — AGENTS",
		title: "Prompt, tools, subagents",
		text: "Coordinators dispatch work to specialized subagents, with streaming and checkpointing.",
	},
	{
		num: "02 — GUARDRAILS",
		title: "Per-tool approval rules",
		text: "Always allow, needs approval, or disabled — approvals land in chat or Slack.",
	},
	{
		num: "03 — RUNS",
		title: "Durable & scheduled",
		text: "Redis-backed runs survive the browser; cron triggers run agents in the background.",
	},
	{
		num: "04 — YOUR INFRA",
		title: "Self-hosted, encrypted",
		text: "AES-GCM keys, Argon2 auth, per-user OAuth tokens — all in your own Postgres.",
	},
];

export function FeatureStrip() {
	return (
		<div className="pm-feature-strip">
			{FEATURES.map((feature) => (
				<div key={feature.num} className="pm-feature-cell">
					<div className="pm-feature-num">{feature.num}</div>
					<div className="pm-feature-title">{feature.title}</div>
					<p className="pm-feature-text">{feature.text}</p>
				</div>
			))}
		</div>
	);
}

const AGENT_CHIPS = [
	{ emoji: "📊", name: "data-analyst", background: "#D0F5EA" },
	{ emoji: "🎧", name: "support-orchestrator", background: "#E4DFFF" },
	{ emoji: "💶", name: "pricing-analyst", background: "#FFF5CC" },
];

export function AgentChips() {
	return (
		<div className="pm-agent-chips">
			<span className="pm-agent-chips-label">agents in production:</span>
			{AGENT_CHIPS.map((chip) => (
				<span key={chip.name} className="pm-agent-chip">
					<span
						className="pm-agent-chip-emoji"
						style={{ background: chip.background }}
					>
						{chip.emoji}
					</span>
					{chip.name}
				</span>
			))}
		</div>
	);
}
