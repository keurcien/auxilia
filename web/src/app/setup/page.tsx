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

	if (isChecking) {
		return null;
	}

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
					<span className="text-2xl">Welcome to auxilia</span>
				</CardTitle>
				<p className="text-sm text-muted-foreground mt-2">
					Create your admin account to get started.
				</p>
			</CardHeader>
			<form onSubmit={handleSubmit}>
				<CardContent className="space-y-4">
					{error && (
						<div className="p-3 text-sm text-destructive bg-destructive/10 rounded-md">
							{error}
						</div>
					)}

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
				<CardFooter>
					<Button
						type="submit"
						className="w-full cursor-pointer"
						disabled={isLoading}
					>
						{isLoading ? "Creating account..." : "Create admin account"}
					</Button>
				</CardFooter>
			</form>
		</Card>
	);
}
