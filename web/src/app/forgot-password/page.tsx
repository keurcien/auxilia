"use client";

import { useState } from "react";
import Link from "next/link";
import { AuthShell } from "@/components/auth/auth-shell";
import {
	AuthErrorAlert,
	AuthField,
	AuthSubmitButton,
} from "@/components/auth/form";
import { getApiErrorMessage } from "@/lib/api/errors";
import { requestPasswordReset } from "@/lib/api/resources/auth";


export default function ForgotPasswordPage() {
	const [email, setEmail] = useState("");
	const [error, setError] = useState<string | null>(null);
	const [isLoading, setIsLoading] = useState(false);
	const [isSent, setIsSent] = useState(false);

	const handleSubmit = async (event: React.FormEvent) => {
		event.preventDefault();
		setError(null);
		setIsLoading(true);
		try {
			await requestPasswordReset(email);
			setIsSent(true);
		} catch (err: unknown) {
			setError(
				getApiErrorMessage(err, "We could not send a password reset email"),
			);
		} finally {
			setIsLoading(false);
		}
	};

	return (
		<AuthShell
			title="Reset your password"
			description="Enter your email and we will send you a secure link to choose a new password."
			footer={
				<Link
					href="/auth"
					className="whitespace-nowrap font-semibold text-petrol hover:text-foreground"
				>
					Back to sign in
				</Link>
			}
		>
			<AuthErrorAlert error={error} />

			{isSent ? (
				<div
					role="status"
					className="rounded-md border border-petrol/20 bg-petrol/5 p-4 text-sm leading-6 text-ink"
				>
					If an account exists for <strong>{email}</strong>, a reset link is
					on its way. Check your inbox and spam folder.
				</div>
			) : (
				<form
					className="flex flex-col gap-4"
					onSubmit={(event) => {
						void handleSubmit(event);
					}}
				>
					<AuthField
						id="email"
						label="Email"
						type="email"
						autoComplete="email"
						placeholder="you@example.com"
						value={email}
						onChange={(event) => {
							setEmail(event.target.value);
						}}
						required
					/>
					<AuthSubmitButton disabled={isLoading}>
						{isLoading ? "Sending link…" : "Send reset link"}
					</AuthSubmitButton>
				</form>
			)}
		</AuthShell>
	);
}
