"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
	cancelCostBackfill,
	getCostBackfill,
	startCostBackfill,
	type CostBackfill,
} from "@/lib/api/resources/thread-costs";
import { isApiError } from "@/lib/api/errors";

export default function ThreadCostBackfill() {
	const [job, setJob] = useState<CostBackfill | null>(null);
	const [start, setStart] = useState("");
	const [end, setEnd] = useState("");
	const [busy, setBusy] = useState(false);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);
	const active = job?.status === "pending" || job?.status === "running";

	useEffect(() => {
		let cancelled = false;
		void getCostBackfill().then((result) => {
			if (!cancelled) setJob(result);
		}).catch((reason: unknown) => {
			if (!cancelled) setError(isApiError(reason) ? reason.detail : "Could not load cost backfill status.");
		}).finally(() => {
			if (!cancelled) setLoading(false);
		});
		return () => { cancelled = true; };
	}, []);

	useEffect(() => {
		if (!active) return;
		let cancelled = false;
		const timer = setTimeout(() => {
			void getCostBackfill().then((result) => {
				if (!cancelled) { setJob(result); setError(null); }
			}).catch((reason: unknown) => {
				if (!cancelled) setError(isApiError(reason) ? reason.detail : "Could not load progress. Refresh to try again.");
			});
		}, 5000);
		return () => { cancelled = true; clearTimeout(timer); };
	}, [active, job]);

	async function submit(event: React.FormEvent) {
		event.preventDefault();
		setBusy(true);
		setError(null);
		try {
			setJob(await startCostBackfill({
				startAt: start ? new Date(`${start}T00:00:00`).toISOString() : null,
				endAt: end ? new Date(`${end}T00:00:00`).toISOString() : null,
			}));
		} catch (reason: unknown) {
			setError(isApiError(reason) ? reason.detail : "Could not start cost backfill.");
		} finally { setBusy(false); }
	}

	async function cancel() {
		setBusy(true);
		try { setJob(await cancelCostBackfill()); setError(null); }
		catch (reason: unknown) { setError(isApiError(reason) ? reason.detail : "Could not cancel cost backfill."); }
		finally { setBusy(false); }
	}

	return (
		<section className="mt-6 space-y-3 border-t border-line pt-5">
			<h3 className="text-sm font-medium">Recalculate thread costs</h3>
			<p className="text-sm text-subtle">Replace saved EUR estimates using current model prices. Dates filter when threads were created, in your local time; leave both blank to include all threads.</p>
			<form onSubmit={submit} className="flex flex-wrap items-end gap-3">
				<label className="space-y-1 text-sm">Created on or after
					<Input type="date" value={start} onChange={(event) => setStart(event.target.value)} disabled={busy || active} />
				</label>
				<label className="space-y-1 text-sm">Created before
					<Input type="date" value={end} onChange={(event) => setEnd(event.target.value)} disabled={busy || active} />
				</label>
				<Button type="submit" disabled={loading || busy || active || (!!start && !!end && start >= end)}>Recalculate costs</Button>
				{active && <Button type="button" variant="outline" onClick={() => { void cancel(); }} disabled={busy}>Cancel</Button>}
			</form>
			{job && job.status !== "idle" && <p role="status" className="text-sm text-subtle">{job.status}: {job.processed} calculated, {job.incomplete} incomplete, {job.skipped} skipped, {job.failed} failed. {job.skipped > 0 && "Busy threads were skipped; run again after they finish."}</p>}
			{job?.lastError && <p className="text-sm text-destructive">Last failure: {job.lastError}</p>}
			{error && <p role="alert" className="text-sm text-destructive">{error}</p>}
		</section>
	);
}
