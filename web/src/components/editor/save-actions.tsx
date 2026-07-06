import { SageButton } from "@/components/ui/sage-button";

interface SaveActionsProps {
	isDirty: boolean;
	isSaving: boolean;
	/** Extra validity gate on top of dirtiness (required fields, valid schedule…). */
	canSave?: boolean;
	onSave: () => void;
	onCancel?: () => void;
	saveLabel?: string;
}

/** Explicit-save button pair: optional Cancel + primary Save. */
export function SaveActions({
	isDirty,
	isSaving,
	canSave = true,
	onSave,
	onCancel,
	saveLabel = "Save changes",
}: SaveActionsProps) {
	return (
		<div className="flex items-center gap-2.5">
			{onCancel && (
				<SageButton
					color="outline"
					onClick={() => {
						onCancel();
					}}
					disabled={isSaving}
				>
					Cancel
				</SageButton>
			)}
			<SageButton
				color="dark"
				onClick={() => {
					onSave();
				}}
				disabled={!isDirty || !canSave || isSaving}
			>
				{isSaving ? "Saving..." : saveLabel}
			</SageButton>
		</div>
	);
}
