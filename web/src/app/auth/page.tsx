"use client";

import { Suspense, useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api/client";
import { getApiErrorMessage } from "@/lib/api/errors";
import { AuthShell } from "@/components/auth/auth-shell";
import {
	AuthErrorAlert,
	AuthField,
	AuthSubmitButton,
} from "@/components/auth/form";

interface AuthProviders {
	password: boolean;
	google: boolean;
	setupRequired: boolean;
}

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
			setError(getApiErrorMessage(err, "An error occurred"));
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

	return (
		<AuthShell
			eyebrow="// WELCOME BACK"
			title="Sign in to your workspace"
			description="Your agents kept working while you were away."
			footer={
				<>
					No account?{" "}
					<span className="font-semibold text-petrol">
						Ask your admin for an invite
					</span>
				</>
			}
		>
			<AuthErrorAlert error={error} />

			{providers?.password && (
				<form
					className="flex flex-col gap-4"
					onSubmit={(e) => {
						void handleSubmit(e);
					}}
				>
					<AuthField
						id="email"
						label="EMAIL"
						type="email"
						placeholder="you@example.com"
						value={email}
						onChange={(e) => {
							setEmail(e.target.value);
						}}
						required
					/>

					<AuthField
						id="password"
						label="PASSWORD"
						type="password"
						placeholder="••••••••••••"
						value={password}
						onChange={(e) => {
							setPassword(e.target.value);
						}}
						required
					/>

					<AuthSubmitButton disabled={isLoading}>
						{isLoading ? "Signing in…" : "Sign in →"}
					</AuthSubmitButton>
				</form>
			)}

			{providers?.password && providers.google && (
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
		</AuthShell>
	);
}

export default function AuthPage() {
	return (
		<Suspense>
			<AuthPageContent />
		</Suspense>
	);
}
