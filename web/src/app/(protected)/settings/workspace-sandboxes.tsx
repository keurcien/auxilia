"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Image from "next/image";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { HeaderButton } from "@/components/layout/subpage-header";
import ResourceInUseDialog from "@/components/resource-in-use-dialog";
import {
	SANDBOX_PROVIDER_ICONS,
	SANDBOX_PROVIDER_LABELS,
} from "@/lib/sandbox-providers";
import { api } from "@/lib/api/client";
import type { BoundAgent } from "@/types/agents";
import type { Sandbox } from "@/types/sandboxes";
import SandboxDialog from "./sandbox-dialog";

interface WorkspaceSandboxesProps {
	onForbidden: () => void;
	/** Reports the registry size so the settings rail can show a count. */
	onCountChange?: (count: number) => void;
}

const isForbidden = (error: unknown): boolean =>
	error instanceof Object && "status" in error && error.status === 403;

export default function WorkspaceSandboxes({
	onForbidden,
	onCountChange,
}: WorkspaceSandboxesProps) {
	const [sandboxes, setSandboxes] = useState<Sandbox[]>([]);
	const [isLoading, setIsLoading] = useState(true);
	const [loadFailed, setLoadFailed] = useState(false);
	const [status, setStatus] = useState<{
		kind: "info" | "error";
		text: string;
	} | null>(null);
	const [dialogOpen, setDialogOpen] = useState(false);
	const [editing, setEditing] = useState<Sandbox | null>(null);
	const [deleteTarget, setDeleteTarget] = useState<{
		sandbox: Sandbox;
		agents: BoundAgent[];
	} | null>(null);
	const [pendingIds, setPendingIds] = useState<ReadonlySet<string>>(new Set());

	const onForbiddenRef = useRef(onForbidden);
	onForbiddenRef.current = onForbidden;
	const onCountChangeRef = useRef(onCountChange);
	onCountChangeRef.current = onCountChange;

	const applySandboxes = useCallback((rows: Sandbox[]) => {
		setSandboxes(rows);
		onCountChangeRef.current?.(rows.length);
	}, []);

	const loadSandboxes = useCallback(async () => {
		setIsLoading(true);
		setLoadFailed(false);
		try {
			const response = await api.get("/sandboxes");
			applySandboxes(response.data as Sandbox[]);
		} catch (error: unknown) {
			if (isForbidden(error)) {
				onForbiddenRef.current();
			}
			setLoadFailed(true);
		} finally {
			setIsLoading(false);
		}
	}, [applySandboxes]);

	useEffect(() => {
		void loadSandboxes();
	}, [loadSandboxes]);

	const setPending = (id: string, pending: boolean) => {
		setPendingIds((prev) => {
			const next = new Set(prev);
			if (pending) {
				next.add(id);
			} else {
				next.delete(id);
			}
			return next;
		});
	};

	const handleDelete = async (sandbox: Sandbox) => {
		setPending(sandbox.id, true);
		try {
			// A sandbox still enabled on agents can't be removed silently —
			// the dialog lists them and asks for an explicit detach + delete.
			const response = await api.get(`/sandboxes/${sandbox.id}/agents`);
			const agents = response.data as BoundAgent[];
			if (agents.length > 0) {
				setDeleteTarget({ sandbox, agents });
				return;
			}
			if (!window.confirm(`Delete "${sandbox.name}"?`)) return;
			await api.delete(`/sandboxes/${sandbox.id}`);
			applySandboxes(sandboxes.filter((s) => s.id !== sandbox.id));
		} catch (error: unknown) {
			if (isForbidden(error)) {
				onForbiddenRef.current();
			} else {
				setStatus({ kind: "error", text: "Could not delete the sandbox." });
			}
		} finally {
			setPending(sandbox.id, false);
		}
	};

	const handleDetachAndDelete = async () => {
		if (!deleteTarget) return;
		const { sandbox } = deleteTarget;
		await api.delete(`/sandboxes/${sandbox.id}?detach_agents=true`);
		applySandboxes(sandboxes.filter((s) => s.id !== sandbox.id));
	};

	const handleSaved = (saved: Sandbox) => {
		setStatus(null);
		const exists = sandboxes.some((s) => s.id === saved.id);
		applySandboxes(
			exists
				? sandboxes.map((s) => (s.id === saved.id ? saved : s))
				: [...sandboxes, saved],
		);
	};

	return (
		<>
			<SandboxDialog
				open={dialogOpen}
				onOpenChange={setDialogOpen}
				sandbox={editing}
				onSaved={handleSaved}
			/>
			<ResourceInUseDialog
				open={deleteTarget !== null}
				onOpenChange={(open) => {
					if (!open) setDeleteTarget(null);
				}}
				resourceLabel="Sandbox"
				resourceName={deleteTarget?.sandbox.name ?? null}
				agents={deleteTarget?.agents ?? []}
				consequence="they lose code execution"
				onConfirm={handleDetachAndDelete}
			/>

			<div className="mb-1.5 flex items-baseline gap-2.5">
				<span className="font-mono text-[10.5px] font-semibold tracking-[0.09em] text-subtle dark:text-panel-dim">
					SANDBOXES
				</span>
				<span className="font-mono text-[10.5px] text-meta dark:text-panel-dim">
					admin
				</span>
				<span className="flex-1" />
				<button
					type="button"
					onClick={() => {
						setEditing(null);
						setDialogOpen(true);
					}}
					className="flex cursor-pointer items-center gap-1.5 rounded-[7px] bg-primary px-4 py-2 text-[12.5px] font-semibold text-primary-foreground transition-opacity hover:opacity-90"
				>
					<Plus className="size-3.5" />
					Add sandbox
				</button>
			</div>
			<p className="mb-3.5 max-w-[640px] text-[13px] leading-[1.55] text-subtle text-pretty dark:text-panel-body">
				Execution backends where agents run code. Register OpenSandbox VMs,
				Cloud Run gateways or Daytona workspaces, then attach one to an agent.
			</p>

			{status && (
				<p
					className={`mb-3 text-[13px] font-medium ${
						status.kind === "error"
							? "text-destructive"
							: "text-subtle dark:text-panel-body"
					}`}
				>
					{status.text}
				</p>
			)}

			<div className="overflow-hidden rounded-[10px] border border-border bg-card dark:border-white/10">
				{isLoading ? (
					<div className="px-4 py-12 text-center text-[14px] font-medium text-faint dark:text-muted-foreground">
						Loading…
					</div>
				) : loadFailed ? (
					<div className="px-4 py-12 text-center">
						<p className="mb-3 text-[14px] font-medium text-faint dark:text-muted-foreground">
							Could not load sandboxes.
						</p>
						<HeaderButton
							className="mx-auto"
							onClick={() => {
								void loadSandboxes();
							}}
						>
							Retry
						</HeaderButton>
					</div>
				) : sandboxes.length === 0 ? (
					<div className="px-4 py-12 text-center text-[14px] font-medium text-faint dark:text-muted-foreground">
						No sandboxes yet. Add one to give agents code execution.
					</div>
				) : (
					sandboxes.map((sandbox) => (
						<div
							key={sandbox.id}
							className="flex items-center gap-3 border-b border-hairline px-4 py-3 transition-colors last:border-b-0 hover:bg-sidebar dark:border-white/5 dark:hover:bg-white/5"
						>
							<span className="flex size-[26px] shrink-0 items-center justify-center rounded-[6px] border border-border bg-card dark:border-white/10">
								<Image
									unoptimized
									width={14}
									height={14}
									src={SANDBOX_PROVIDER_ICONS[sandbox.provider]}
									alt={SANDBOX_PROVIDER_LABELS[sandbox.provider]}
									className="rounded-[2px] object-contain"
								/>
							</span>
							<div className="min-w-0 flex-1">
								<div className="flex flex-wrap items-center gap-2">
									<span className="text-[13.5px] font-semibold text-foreground">
										{sandbox.name}
									</span>
									<span className="rounded-[4px] bg-hover px-2 py-0.5 font-mono text-[9.5px] font-semibold tracking-[0.06em] text-subtle uppercase dark:bg-white/10 dark:text-panel-dim">
										{SANDBOX_PROVIDER_LABELS[sandbox.provider]}
									</span>
								</div>
								<span className="mt-0.5 block truncate font-mono text-[10.5px] text-meta dark:text-panel-dim">
									{sandbox.url}
								</span>
							</div>
							<button
								type="button"
								title="Edit sandbox"
								aria-label={`Edit ${sandbox.name}`}
								onClick={() => {
									setEditing(sandbox);
									setDialogOpen(true);
								}}
								className="flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-[7px] text-meta transition-colors hover:bg-hover hover:text-foreground dark:hover:bg-white/10"
							>
								<Pencil className="size-3.5" />
							</button>
							<button
								type="button"
								title="Delete sandbox"
								aria-label={`Delete ${sandbox.name}`}
								disabled={pendingIds.has(sandbox.id)}
								onClick={() => {
									void handleDelete(sandbox);
								}}
								className="flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-[7px] text-meta transition-colors hover:bg-[#FBEFED] hover:text-[#B04A3A] disabled:cursor-default disabled:opacity-50 dark:hover:bg-rose-950"
							>
								<Trash2 className="size-3.5" />
							</button>
						</div>
					))
				)}
			</div>
		</>
	);
}
