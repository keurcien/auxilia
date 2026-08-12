"use client";

import { useEffect, useState } from "react";
import { Copy, Check, KeyRound, Plus, Trash2 } from "lucide-react";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import CreateTokenDialog, { type PersonalAccessToken } from "./create-token-dialog";
import WorkspaceModels from "./workspace-models";
import { SubpageHeader } from "@/components/layout/subpage-header";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { api } from "@/lib/api/client";
import { useQueryParamState } from "@/hooks/use-query-param-state";
import { useUserStore } from "@/stores/user-store";

function formatDate(dateStr: string): string {
	return new Date(dateStr)
		.toLocaleDateString("en-US", {
			year: "numeric",
			month: "short",
			day: "numeric",
		})
		.toLowerCase();
}

/** One-time reveal of a freshly created token (design 18a banner). */
function TokenRevealBanner({ plaintext }: { plaintext: string }) {
	const [copied, setCopied] = useState(false);

	const handleCopy = () => {
		void navigator.clipboard.writeText(plaintext).then(() => {
			setCopied(true);
			setTimeout(() => {
				setCopied(false);
			}, 2000);
		});
	};

	return (
		<div className="mb-3 flex items-center gap-3 rounded-[10px] border border-sparkline bg-[#F2F8F8] px-4 py-[13px] dark:border-petrol/40 dark:bg-petrol/10">
			<span className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-[#DCE9EB] bg-white text-petrol dark:border-white/10 dark:bg-white/10 dark:text-panel-terminal">
				<KeyRound className="size-[15px]" />
			</span>
			<span className="min-w-0 flex-1">
				<span className="block text-[13px] font-semibold text-foreground">
					Copy your new token now — you won&apos;t be able to see it again.
				</span>
				<span className="mt-[3px] block truncate font-mono text-[12px] text-petrol dark:text-panel-terminal">
					{plaintext}
				</span>
			</span>
			<button
				type="button"
				onClick={handleCopy}
				className="inline-flex shrink-0 cursor-pointer items-center gap-1.5 rounded-[7px] bg-petrol px-3.5 py-[7px] text-[12.5px] font-semibold text-white transition-opacity hover:opacity-90"
			>
				{copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
				{copied ? "Copied!" : "Copy"}
			</button>
		</div>
	);
}

type SettingsTab = "tokens" | "models";

export default function SettingsPage() {
	const [tokens, setTokens] = useState<PersonalAccessToken[]>([]);
	const [isLoading, setIsLoading] = useState(true);
	const [revealedToken, setRevealedToken] = useState<string | null>(null);
	const [modelCount, setModelCount] = useState<number | null>(null);
	const [errorDialogOpen, setErrorDialogOpen] = useState(false);
	const [createDialogOpen, setCreateDialogOpen] = useState(false);
	const user = useUserStore((state) => state.user);
	const fetchUser = useUserStore((state) => state.fetchUser);
	const isAdmin = user?.role === "admin";

	const [tabParam, setTab] = useQueryParamState("tab", "tokens");
	const tab: SettingsTab =
		tabParam === "models" && isAdmin ? "models" : "tokens";

	useEffect(() => {
		void fetchUser();
	}, [fetchUser]);

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
		void fetchTokens();
	}, []);

	const handleDelete = async (token: PersonalAccessToken) => {
		const confirmed = window.confirm(
			"Are you sure you want to revoke this token? Any services using it will lose access.",
		);
		if (!confirmed) return;

		try {
			await api.delete(`/auth/tokens/${token.id}`);
			setTokens((prev) => prev.filter((t) => t.id !== token.id));
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

	const tokenColumns: DataTableColumn<PersonalAccessToken>[] = [
		{
			key: "token",
			header: "Token",
			width: "minmax(0, 1fr)",
			cell: (token) => (
				<div className="min-w-0">
					<span className="block truncate text-[13.5px] font-semibold text-foreground">
						{token.name}
					</span>
					<span className="mt-0.5 block truncate font-mono text-[10.5px] text-meta dark:text-panel-dim">
						{token.prefix}…
					</span>
				</div>
			),
		},
		{
			key: "created",
			header: "Created",
			width: "160px",
			mobileWidth: "auto",
			cell: (token) => (
				<span className="font-mono text-[11px] text-subtle dark:text-muted-foreground">
					{formatDate(token.createdAt)}
				</span>
			),
		},
		{
			key: "actions",
			header: "",
			width: "40px",
			cell: (token) => (
				<button
					type="button"
					title="Revoke token"
					aria-label={`Revoke ${token.name}`}
					onClick={() => {
						void handleDelete(token);
					}}
					className="flex size-7 cursor-pointer items-center justify-center rounded-[7px] text-meta transition-colors hover:bg-[#FBEFED] hover:text-[#B04A3A] dark:hover:bg-rose-950"
				>
					<Trash2 className="size-3.5" />
				</button>
			),
		},
	];

	const railTabClass = (active: boolean) =>
		`flex cursor-pointer items-center gap-2 border-l-2 px-3 py-[7px] text-left text-[13px] transition-colors ${
			active
				? "border-petrol font-semibold text-foreground"
				: "border-transparent font-medium text-subtle hover:text-foreground dark:text-panel-body"
		}`;

	return (
		<div className="flex h-svh min-w-0 flex-1 flex-col bg-background animate-in fade-in duration-300">
			<SubpageHeader trail={[{ label: "workspace" }, { label: "settings" }]} />

			<ForbiddenErrorDialog
				open={errorDialogOpen}
				onOpenChange={setErrorDialogOpen}
				title="Insufficient privileges"
				message="You are not allowed to perform this action."
			/>
			<CreateTokenDialog
				open={createDialogOpen}
				onOpenChange={setCreateDialogOpen}
				onTokenCreated={(token, plaintext) => {
					setTokens((prev) => [token, ...prev]);
					setRevealedToken(plaintext);
				}}
			/>

			<div className="flex min-h-0 flex-1">
				{/* Left rail: title + vertical section tabs */}
				<div className="w-[200px] flex-none pl-7 pt-8">
					<h1 className="mb-[18px] pl-3.5 font-display text-[22px] font-bold tracking-[-0.03em] text-foreground">
						Settings
					</h1>
					<div className="flex flex-col gap-0.5">
						<button
							type="button"
							className={railTabClass(tab === "tokens")}
							onClick={() => {
								setTab("tokens");
							}}
						>
							Access tokens
							<span className="font-mono text-[10.5px] font-normal text-meta dark:text-panel-dim">
								{tokens.length}
							</span>
						</button>
						{isAdmin && (
							<button
								type="button"
								className={railTabClass(tab === "models")}
								onClick={() => {
									setTab("models");
								}}
							>
								Models
								{modelCount !== null && (
									<span className="font-mono text-[10.5px] font-normal text-meta dark:text-panel-dim">
										{modelCount}
									</span>
								)}
							</button>
						)}
					</div>
				</div>

				{/* Content */}
				<div className="min-w-0 flex-1 overflow-y-auto px-9 py-8 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
					<div className="mx-auto max-w-[800px]">
						{/* Access tokens — kept mounted so the rail count stays live */}
						<section className={tab === "tokens" ? "" : "hidden"}>
							<div className="mb-1.5 flex items-baseline gap-2.5">
								<span className="font-mono text-[10.5px] font-semibold tracking-[0.09em] text-subtle dark:text-panel-dim">
									PERSONAL ACCESS TOKENS
								</span>
								<span className="flex-1" />
								<button
									type="button"
									onClick={() => {
										setCreateDialogOpen(true);
									}}
									className="flex cursor-pointer items-center gap-1.5 rounded-[7px] bg-primary px-4 py-2 text-[12.5px] font-semibold text-primary-foreground transition-opacity hover:opacity-90"
								>
									<Plus className="size-3.5" />
									Generate token
								</button>
							</div>
							<p className="mb-3.5 max-w-[620px] text-[13px] leading-[1.55] text-subtle dark:text-panel-body">
								Authenticate external services against the API — n8n, the
								invoke endpoint, scripts. Tokens act as you.
							</p>

							{revealedToken && <TokenRevealBanner plaintext={revealedToken} />}

							<DataTable
								columns={tokenColumns}
								rows={tokens}
								rowKey={(token) => token.id}
								isLoading={isLoading}
								emptyMessage={
									<span>
										No personal access tokens yet.
										<br />
										<span className="text-[13px] font-normal">
											Generate a token to authenticate external services.
										</span>
									</span>
								}
							/>
						</section>

						{/* Workspace models — admin only */}
						{isAdmin && (
							<section className={tab === "models" ? "" : "hidden"}>
								<WorkspaceModels
									onForbidden={() => {
										setErrorDialogOpen(true);
									}}
									onCountChange={setModelCount}
								/>
							</section>
						)}
					</div>
				</div>
			</div>
		</div>
	);
}
