"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
	Dialog,
	DialogButton,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { getApiErrorMessage } from "@/lib/api/errors";
import { getUsageSettings, updateUsageSettings } from "@/lib/api/resources/usage";
import type { UsageSettings } from "@/types/usage";

export function UsageSettingsDialog({
	open,
	onOpenChange,
	onSaved,
}: {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	onSaved: (settings: UsageSettings) => void;
}) {
	const [settings, setSettings] = useState<UsageSettings | null>(null);
	const [currency, setCurrency] = useState("EUR");
	const [rate, setRate] = useState("");
	const [budget, setBudget] = useState("");
	const [saving, setSaving] = useState(false);

	useEffect(() => {
		if (!open) return;
		let cancelled = false;
		getUsageSettings()
			.then((loaded) => {
				if (cancelled) return;
				setSettings(loaded);
				setCurrency(loaded.currency);
				setRate(String(loaded.usdRate));
				setBudget(loaded.monthlyBudget === null ? "" : String(loaded.monthlyBudget));
			})
			.catch((error: unknown) => {
				toast.error(getApiErrorMessage(error, "Failed to load usage settings."));
			});
		return () => {
			cancelled = true;
		};
	}, [open]);

	const isUsd = currency === "USD";
	const parsedRate = isUsd ? 1 : Number(rate.replace(",", "."));
	const parsedBudget = budget.trim() === "" ? null : Number(budget.replace(",", "."));
	const rateValid = Number.isFinite(parsedRate) && parsedRate > 0;
	const budgetValid = parsedBudget === null || (Number.isFinite(parsedBudget) && parsedBudget > 0);

	const handleSave = async () => {
		setSaving(true);
		try {
			const saved = await updateUsageSettings({
				currency,
				usdRate: parsedRate,
				monthlyBudget: parsedBudget,
			});
			toast.success("Usage settings saved");
			onSaved(saved);
			onOpenChange(false);
		} catch (error) {
			toast.error(getApiErrorMessage(error, "Failed to save usage settings."));
		} finally {
			setSaving(false);
		}
	};

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent>
				<DialogHeader>
					<DialogTitle>Usage settings</DialogTitle>
					<DialogDescription>
						Model prices are in US dollars. Costs are shown in the workspace
						currency with the rate below, and compared with the monthly budget.
					</DialogDescription>
				</DialogHeader>

				<form
					className="grid gap-4"
					onSubmit={(event) => {
						event.preventDefault();
						void handleSave();
					}}
				>
					<div className="grid grid-cols-[120px_minmax(0,1fr)] gap-3">
						<div className="grid gap-1.5">
							<Label htmlFor="usage-currency">Currency</Label>
							<select
								id="usage-currency"
								value={currency}
								disabled={!settings}
								onChange={(event) => {
									setCurrency(event.target.value);
								}}
								className="h-9 rounded-md border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 dark:bg-input/30"
							>
								{(settings?.supportedCurrencies ?? [currency]).map((code) => (
									<option key={code} value={code}>
										{code}
									</option>
								))}
							</select>
						</div>
						<div className="grid gap-1.5">
							<Label htmlFor="usage-rate">1 USD in {currency}</Label>
							<Input
								id="usage-rate"
								inputMode="decimal"
								value={isUsd ? "1" : rate}
								disabled={isUsd || !settings}
								aria-invalid={!rateValid}
								onChange={(event) => {
									setRate(event.target.value);
								}}
							/>
						</div>
					</div>

					<div className="grid gap-1.5">
						<Label htmlFor="usage-budget">Monthly budget ({currency})</Label>
						<Input
							id="usage-budget"
							inputMode="decimal"
							placeholder="No budget"
							value={budget}
							disabled={!settings}
							aria-invalid={!budgetValid}
							onChange={(event) => {
								setBudget(event.target.value);
							}}
						/>
						<p className="text-[12px] text-meta dark:text-panel-dim">
							The usage page warns when this month is on track to exceed it.
							Leave empty for no budget.
						</p>
					</div>

					<DialogFooter>
						<DialogButton
							variant="outline"
							onClick={() => {
								onOpenChange(false);
							}}
						>
							Cancel
						</DialogButton>
						<DialogButton type="submit" disabled={!settings || saving || !rateValid || !budgetValid}>
							{saving ? "Saving…" : "Save"}
						</DialogButton>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
