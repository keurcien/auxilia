"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Image from "next/image";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
	Card,
	CardContent,
	CardFooter,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { api } from "@/lib/api/client";

type AuthMode = "signin" | "signup";

interface AuthProviders {
	password: boolean;
	google: boolean;
}

export default function AuthPage() {
	const router = useRouter();
	const [mode, setMode] = useState<AuthMode>("signin");
	const [isLoading, setIsLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [providers, setProviders] = useState<AuthProviders | null>(null);

	const [email, setEmail] = useState("");
	const [password, setPassword] = useState("");
	const [name, setName] = useState("");

	useEffect(() => {
		const fetchProviders = async () => {
			try {
				const response = await api.get("/auth/providers");
				setProviders(response.data);
			} catch {
				// Default to password-only if providers endpoint fails
				setProviders({ password: true, google: false });
			}
		};
		fetchProviders();
	}, []);

	const handleSubmit = async (e: React.FormEvent) => {
		e.preventDefault();
		setError(null);
		setIsLoading(true);

		try {
			if (mode === "signup") {
				await api.post("/auth/signup", { email, password, name });
			} else {
				await api.post("/auth/signin", { email, password });
			}
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

	const toggleMode = () => {
		setMode(mode === "signin" ? "signup" : "signin");
		setError(null);
	};

	return (
		<Card className="w-full max-w-md">
			<CardHeader className="text-center flex flex-col items-center">
				<CardTitle className="text-2xl flex flex-col items-center justify-center">
					<Image
						src="https://storage.googleapis.com/choose-assets/logo.png"
						alt="auxilia"
						width={48}
						height={48}
						className="mb-2"
					/>
					<span className="text-2xl">auxilia</span>
				</CardTitle>
			</CardHeader>
			<form onSubmit={handleSubmit}>
				<CardContent className="space-y-4">
					{error && (
						<div className="p-3 text-sm text-destructive bg-destructive/10 rounded-md">
							{error}
						</div>
					)}

					{mode === "signup" && (
						<div className="space-y-2">
							<Label htmlFor="name">Name</Label>
							<Input
								id="name"
								type="text"
								placeholder="John Doe"
								value={name}
								onChange={(e) => setName(e.target.value)}
							/>
						</div>
					)}

					<div className="space-y-2">
						<Label htmlFor="email">Email</Label>
						<Input
							id="email"
							type="email"
							placeholder="you@example.com"
							value={email}
							onChange={(e) => setEmail(e.target.value)}
							required
						/>
					</div>

					<div className="space-y-2">
						<Label htmlFor="password">Password</Label>
						<Input
							id="password"
							type="password"
							placeholder="••••••••"
							value={password}
							onChange={(e) => setPassword(e.target.value)}
							required
						/>

						<div className="h-5">
							<p
								className={`text-xs transition-all duration-300 ease-in-out ${
									password.length > 0 && password.length < 8
										? "opacity-100 translate-y-0"
										: "opacity-0 -translate-y-1 pointer-events-none"
								}`}
							>
								Password must be at least 8 characters
							</p>
						</div>
					</div>
				</CardContent>
				<CardFooter className="flex flex-col gap-4">
					<Button
						type="submit"
						className="w-full cursor-pointer"
						disabled={isLoading}
					>
						{isLoading
							? "Loading..."
							: mode === "signin"
								? "Sign In"
								: "Sign Up"}
					</Button>

					{providers?.google && (
						<>
							<div className="relative w-full">
								<div className="absolute inset-0 flex items-center">
									<span className="w-full border-t" />
								</div>
								<div className="relative flex justify-center text-xs uppercase">
									<span className="bg-card px-2 text-muted-foreground">
										Or continue with
									</span>
								</div>
							</div>

							<Button
								type="button"
								variant="outline"
								className="w-full cursor-pointer"
								onClick={() => {
									window.location.href = "/api/backend/auth/google";
								}}
							>
								<svg
									className="mr-2 h-4 w-4"
									viewBox="0 0 24 24"
									xmlns="http://www.w3.org/2000/svg"
								>
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
								{mode === "signin"
									? "Sign in with Google"
									: "Sign up with Google"}
							</Button>
						</>
					)}

					<p className="text-sm text-muted-foreground text-center">
						{mode === "signin" ? (
							<>
								No account yet?{" "}
								<button
									type="button"
									onClick={toggleMode}
									className="text-primary hover:underline cursor-pointer"
								>
									Sign up
								</button>
							</>
						) : (
							<>
								Already have an account?{" "}
								<button
									type="button"
									onClick={toggleMode}
									className="text-primary hover:underline cursor-pointer"
								>
									Sign in
								</button>
							</>
						)}
					</p>
				</CardFooter>
			</form>
		</Card>
	);
}
