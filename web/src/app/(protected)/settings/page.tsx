"use client";

import { useEffect, useState } from "react";
import { Trash2, Plus, KeyRound } from "lucide-react";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import CreateTokenDialog from "./create-token-dialog";
import { Button } from "@/components/ui/button";
import { PageContainer } from "@/components/layout/page-container";
import { api } from "@/lib/api/client";

interface PersonalAccessToken {
	id: string;
	name: string;
	prefix: string;
	createdAt: string;
}

function formatDate(dateStr: string): string {
	return new Date(dateStr).toLocaleDateString("en-US", {
		year: "numeric",
		month: "short",
		day: "numeric",
	});
}

export default function SettingsPage() {
	const [tokens, setTokens] = useState<PersonalAccessToken[]>([]);
	const [isLoading, setIsLoading] = useState(true);
	const [errorDialogOpen, setErrorDialogOpen] = useState(false);
	const [createDialogOpen, setCreateDialogOpen] = useState(false);

	useEffect(() => {
		const fetchTokens = async () => {
			try {
				const response = await api.get("/auth/tokens");
				setTokens(response.data);
			} catch (error: unknown) {
				if (
					error instanceof Object &&
					"status" in error &&
					error.status === 403
				) {
					setErrorDialogOpen(true);
				} else {
					console.error("Error fetching tokens:", error);
				}
			} finally {
				setIsLoading(false);
			}
		};
		fetchTokens();
	}, []);

	const handleDelete = async (tokenId: string) => {
		const confirmed = window.confirm(
			"Are you sure you want to revoke this token? Any services using it will lose access.",
		);
		if (!confirmed) return;

		try {
			await api.delete(`/auth/tokens/${tokenId}`);
			setTokens((prev) => prev.filter((t) => t.id !== tokenId));
		} catch (error: unknown) {
			if (
				error instanceof Object &&
				"status" in error &&
				error.status === 403
			) {
				setErrorDialogOpen(true);
			} else {
				console.error("Error deleting token:", error);
			}
		}
	};

	const handleCreate = () => {
		try {
			setCreateDialogOpen(true);
		} catch (error: unknown) {
			if (
				error instanceof Object &&
				"status" in error &&
				error.status === 403
			) {
				setErrorDialogOpen(true);
			}
		}
	};

	return (
		<PageContainer>
			<ForbiddenErrorDialog
				open={errorDialogOpen}
				onOpenChange={setErrorDialogOpen}
				title="Insufficient privileges"
				message="You are not allowed to perform this action."
			/>
			<CreateTokenDialog
				open={createDialogOpen}
				onOpenChange={setCreateDialogOpen}
				onTokenCreated={(token) =>
					setTokens((prev) => [token, ...prev])
				}
			/>

			<div className="flex items-center justify-between my-8">
				<h1 className="font-primary font-extrabold text-2xl md:text-4xl tracking-tighter text-[#2A2F2D] dark:text-white">
					Settings
				</h1>
				<Button
					className="flex items-center gap-2 py-2.5 md:py-5 bg-[#2A2F2D] text-sm md:text-base font-semibold text-white rounded-[14px] hover:opacity-90 transition-opacity cursor-pointer shadow-[0_4px_14px_rgba(118,181,160,0.14)] border-none"
					onClick={handleCreate}
				>
					<Plus className="w-4 h-4" />
					Generate token
				</Button>
			</div>

			<h2 className="font-primary font-bold text-lg tracking-tight text-[#2A2F2D] dark:text-white mb-2">
				Personal access tokens
			</h2>

			<div className="rounded-[20px] border bg-card overflow-hidden">
				<table className="w-full">
					<thead>
						<tr className="border-b bg-muted/50">
							<th className="px-6 py-3 text-left text-xs text-muted-foreground font-semibold uppercase tracking-wider">
								Token
							</th>
							<th className="px-6 py-3 text-left text-xs text-muted-foreground font-semibold uppercase tracking-wider">
								Created
							</th>
							<th className="w-16 px-6 py-3" />
						</tr>
					</thead>
					<tbody>
						{isLoading ? (
							<tr>
								<td
									colSpan={3}
									className="px-6 py-12 text-center text-muted-foreground"
								>
									Loading...
								</td>
							</tr>
						) : tokens.length === 0 ? (
							<tr>
								<td
									colSpan={3}
									className="px-6 py-12 text-center"
								>
									<div className="flex flex-col items-center gap-2">
										<KeyRound className="h-8 w-8 text-muted-foreground/50" />
										<p className="text-muted-foreground">
											No personal access tokens yet.
										</p>
										<p className="text-sm text-muted-foreground/70">
											Generate a token to authenticate external services.
										</p>
									</div>
								</td>
							</tr>
						) : (
							tokens.map((token) => (
								<tr
									key={token.id}
									className="border-b last:border-b-0 hover:bg-muted/30 transition-colors"
								>
									<td className="px-6 py-4">
										<div className="flex flex-col gap-0.5">
											<span className="text-sm font-medium text-foreground">
												{token.name}
											</span>
											<span className="text-xs text-muted-foreground font-mono">
												{token.prefix}...
											</span>
										</div>
									</td>
									<td className="px-6 py-4">
										<span className="text-sm text-muted-foreground">
											{formatDate(token.createdAt)}
										</span>
									</td>
									<td className="px-6 py-4">
										<Button
											variant="ghost"
											size="icon"
											className="h-8 w-8 text-muted-foreground hover:text-destructive cursor-pointer"
											onClick={() => handleDelete(token.id)}
										>
											<Trash2 className="h-4 w-4" />
										</Button>
									</td>
								</tr>
							))
						)}
					</tbody>
				</table>
			</div>
		</PageContainer>
	);
}
