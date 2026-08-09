"use client";

import { Suspense, useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api/client";

interface AuthProviders {
	password: boolean;
	google: boolean;
	setupRequired: boolean;
}

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

function GoogleIcon() {
	return (
		<svg className="h-4 w-4" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
			<path
				d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
				fill="#4285F4"
			/>
			<path
				d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
				fill="#34A853"
			/>
			<path
				d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
				fill="#FBBC05"
			/>
			<path
				d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
				fill="#EA4335"
			/>
		</svg>
	);
}

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
function LoginShowcase() {
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
		<div className="relative flex flex-col gap-5">
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

function AuthPageContent() {
	const router = useRouter();
	const searchParams = useSearchParams();
	const [isLoading, setIsLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [providers, setProviders] = useState<AuthProviders | null>(null);

	const [email, setEmail] = useState("");
	const [password, setPassword] = useState("");

	useEffect(() => {
		const errorParam = searchParams.get("error");
		if (errorParam === "no_invite") {
			setError(
				"No invite found for your Google account. Please ask your workspace admin for an invite.",
			);
		}
	}, [searchParams]);

	useEffect(() => {
		const fetchProviders = async () => {
			try {
				const response = await api.get("/auth/providers");
				const data = response.data as AuthProviders;
				setProviders(data);
				if (data.setupRequired) {
					router.replace("/setup");
				}
			} catch {
				setProviders({ password: true, google: false, setupRequired: false });
			}
		};
		fetchProviders();
	}, [router]);

	const handleSubmit = async (e: React.FormEvent) => {
		e.preventDefault();
		setError(null);
		setIsLoading(true);

		try {
			await api.post("/auth/signin", { email, password });
			router.push("/agents");
		} catch (err: unknown) {
			if (err && typeof err === "object" && "response" in err) {
				const axiosError = err as { response?: { data?: { detail?: string } } };
				setError(axiosError.response?.data?.detail || "An error occurred");
			} else {
				setError("An error occurred");
			}
		} finally {
			setIsLoading(false);
		}
	};

	const signInWithGoogle = () => {
		window.location.href = "/api/backend/auth/google";
	};

	if (providers?.setupRequired) {
		return null;
	}

	const fieldLabelClass =
		"mb-[7px] block font-mono text-[10.5px] font-semibold tracking-[0.09em] text-label";
	const fieldInputClass =
		"w-full rounded-md border border-input bg-canvas px-4 py-3 text-[14.5px] font-medium text-ink outline-none transition-[border-color,box-shadow] placeholder:text-meta focus:border-petrol focus:shadow-[0_0_0_3px_rgba(22,96,110,0.10)]";

	return (
		<div className="flex min-h-full">
			{/* Left: form */}
			<div className="flex min-w-0 flex-1 flex-col py-10">
				<div className="flex items-center gap-2.5 px-8 lg:px-14">
					{/* eslint-disable-next-line @next/next/no-img-element -- local SVG, next/image blocks SVG sources */}
					<img src="/logo.svg" alt="auxilia" width={25} height={25} />
					<span className="font-display text-xl font-bold tracking-[-0.02em]">
						auxilia
					</span>
					<span className="ml-1 rounded-sm bg-petrol-chip px-1.5 py-0.5 font-mono text-[11px] text-petrol">
						v1.x
					</span>
				</div>
				<div className="mx-auto flex w-full max-w-[420px] flex-1 flex-col justify-center px-8">
					<div className="font-mono text-xs font-medium tracking-[0.06em] text-petrol">
						{"// WELCOME BACK"}
					</div>
					<h1 className="mt-4 font-display text-[40px] font-bold leading-[1.05] tracking-[-0.035em]">
						Sign in to your workspace
					</h1>
					<p className="mt-3.5 text-[15px] leading-[1.6] text-body">
						Your agents kept working while you were away.
					</p>

					<div className="mt-9 flex flex-col gap-4">
						{error && (
							<div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
								{error}
							</div>
						)}

						{providers?.password && (
							<form
								className="flex flex-col gap-4"
								onSubmit={(e) => {
									void handleSubmit(e);
								}}
							>
								<div>
									<label htmlFor="email" className={fieldLabelClass}>
										EMAIL
									</label>
									<input
										id="email"
										type="email"
										placeholder="you@example.com"
										value={email}
										onChange={(e) => {
											setEmail(e.target.value);
										}}
										required
										className={fieldInputClass}
									/>
								</div>

								<div>
									<label htmlFor="password" className={fieldLabelClass}>
										PASSWORD
									</label>
									<input
										id="password"
										type="password"
										placeholder="••••••••••••"
										value={password}
										onChange={(e) => {
											setPassword(e.target.value);
										}}
										required
										className={fieldInputClass}
									/>
								</div>

								<button
									type="submit"
									disabled={isLoading}
									className="mt-1.5 cursor-pointer rounded-md bg-ink p-3.5 text-[15px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-60"
								>
									{isLoading ? "Signing in…" : "Sign in →"}
								</button>
							</form>
						)}

						{providers?.password && providers?.google && (
							<div className="my-1 flex items-center gap-3">
								<span className="h-px flex-1 bg-rail" />
								<span className="font-mono text-[10.5px] text-meta">OR</span>
								<span className="h-px flex-1 bg-rail" />
							</div>
						)}

						{providers?.google && (
							<button
								type="button"
								onClick={signInWithGoogle}
								className="flex cursor-pointer items-center justify-center gap-2.5 rounded-md border border-input bg-canvas p-3 text-[14.5px] font-semibold text-ink transition-colors hover:border-border-hover"
							>
								<GoogleIcon />
								Continue with Google
							</button>
						)}
					</div>

					<p className="mt-7 text-[13.5px] text-label">
						No account?{" "}
						<span className="font-semibold text-petrol">
							Ask your admin for an invite
						</span>
					</p>
				</div>
				<div className="flex items-center justify-between px-8 font-mono text-[11px] text-meta lg:px-14">
					<span>self-hosted</span>
					<span>AGPL-3.0</span>
				</div>
			</div>

			{/* Right: dark showcase panel */}
			<div className="relative hidden w-[46%] flex-none flex-col justify-center gap-6 overflow-hidden bg-panel px-14 py-16 lg:flex">
				<div
					className="absolute inset-0"
					style={{
						backgroundImage:
							"linear-gradient(var(--pm-panel-grid) 1px, transparent 1px), linear-gradient(90deg, var(--pm-panel-grid) 1px, transparent 1px)",
						backgroundSize: "40px 40px",
					}}
				/>
				<div className="relative font-mono text-xs font-medium tracking-[0.06em] text-panel-terminal">
					{"// AGENTS THAT WORK LIKE YOUR TEAM"}
				</div>
				<LoginShowcase />
			</div>
		</div>
	);
}

export default function AuthPage() {
	return (
		<Suspense>
			<AuthPageContent />
		</Suspense>
	);
}
