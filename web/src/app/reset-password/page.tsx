"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { AuthShell } from "@/components/auth/auth-shell";
import {
	AuthErrorAlert,
	AuthField,
	AuthSubmitButton,
} from "@/components/auth/form";
import { getApiErrorMessage } from "@/lib/api/errors";
import { resetPassword } from "@/lib/api/resources/auth";


function ResetPasswordContent() {
	const searchParams = useSearchParams();
	const token = searchParams.get("token");
	const [password, setPassword] = useState("");
	const [confirmation, setConfirmation] = useState("");
	const [error, setError] = useState<string | null>(
		token ? null : "This reset link is invalid or incomplete",
	);
	const [isLoading, setIsLoading] = useState(false);
	const [isComplete, setIsComplete] = useState(false);

	const handleSubmit = async (event: React.FormEvent) => {
		event.preventDefault();
		if (!token) return;
		if (password !== confirmation) {
			setError("Passwords do not match");
			return;
		}
		setError(null);
		setIsLoading(true);
		try {
			await resetPassword(token, password);
			setIsComplete(true);
		} catch (err: unknown) {
			setError(
				getApiErrorMessage(
					err,
					"This reset link is invalid or has expired",
				),
			);
		} finally {
			setIsLoading(false);
		}
	};

	return (
		<AuthShell
			title={isComplete ? "Password updated" : "Choose a new password"}
			description={
				isComplete
					? "Your new password is ready to use."
					: "Use at least 8 characters. Your reset link can only be used once."
			}
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

			{isComplete ? (
				<Link
					href="/auth"
					className="flex whitespace-nowrap rounded-md bg-ink p-3.5 text-center text-[15px] font-semibold text-white transition-opacity hover:opacity-90"
				>
					<span className="w-full">Sign in with your new password</span>
				</Link>
			) : (
				<form
					className="flex flex-col gap-4"
					onSubmit={(event) => {
						void handleSubmit(event);
					}}
				>
					<AuthField
						id="password"
						label="New password"
						type="password"
						autoComplete="new-password"
						placeholder="••••••••••••"
						minLength={8}
						value={password}
						onChange={(event) => {
							setPassword(event.target.value);
						}}
						required
					/>
					<AuthField
						id="password-confirmation"
						label="Confirm new password"
						type="password"
						autoComplete="new-password"
						placeholder="••••••••••••"
						minLength={8}
						value={confirmation}
						onChange={(event) => {
							setConfirmation(event.target.value);
						}}
						required
					/>
					<AuthSubmitButton disabled={isLoading || !token}>
						{isLoading ? "Updating password…" : "Update password"}
					</AuthSubmitButton>
				</form>
			)}
		</AuthShell>
	);
}

export default function ResetPasswordPage() {
	return (
		<Suspense>
			<ResetPasswordContent />
		</Suspense>
	);
}
