"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api/client";
import { getApiErrorMessage } from "@/lib/api/errors";
import { AuthShell } from "@/components/auth/auth-shell";
import {
	AuthErrorAlert,
	AuthField,
	AuthSubmitButton,
} from "@/components/auth/form";

export default function SetupPage() {
	const router = useRouter();
	const [isLoading, setIsLoading] = useState(false);
	const [isChecking, setIsChecking] = useState(true);
	const [error, setError] = useState<string | null>(null);

	const [email, setEmail] = useState("");
	const [password, setPassword] = useState("");
	const [name, setName] = useState("");

	useEffect(() => {
		const checkSetup = async () => {
			try {
				const response = await api.get("/auth/setup/status");
				if (!response.data.setupRequired) {
					router.replace("/auth");
				} else {
					setIsChecking(false);
				}
			} catch {
				setIsChecking(false);
			}
		};
		checkSetup();
	}, [router]);

	const handleSubmit = async (e: React.FormEvent) => {
		e.preventDefault();
		setError(null);
		setIsLoading(true);

		try {
			await api.post("/auth/setup", { email, password, name });
			router.push("/agents");
		} catch (err: unknown) {
			setError(getApiErrorMessage(err, "An error occurred"));
		} finally {
			setIsLoading(false);
		}
	};

	if (isChecking) {
		return null;
	}

	return (
		<AuthShell
			eyebrow="// FIRST RUN"
			title="Set up your workspace"
			description="Create the admin account for this workspace to get started."
			footer={
				<>
					You&apos;ll be able to{" "}
					<span className="font-semibold text-petrol">invite your team</span>{" "}
					once you&apos;re in
				</>
			}
		>
			<AuthErrorAlert error={error} />

			<form
				className="flex flex-col gap-4"
				onSubmit={(e) => {
					void handleSubmit(e);
				}}
			>
				<AuthField
					id="name"
					label="NAME"
					type="text"
					placeholder="John Doe"
					value={name}
					onChange={(e) => {
						setName(e.target.value);
					}}
				/>

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
				>
					<div className="mt-[7px] h-4">
						<p
							className={`text-xs text-label transition-all duration-300 ease-in-out ${
								password.length > 0 && password.length < 8
									? "opacity-100 translate-y-0"
									: "opacity-0 -translate-y-1 pointer-events-none"
							}`}
						>
							Password must be at least 8 characters
						</p>
					</div>
				</AuthField>

				<AuthSubmitButton disabled={isLoading}>
					{isLoading ? "Creating account…" : "Create admin account →"}
				</AuthSubmitButton>
			</form>
		</AuthShell>
	);
}
