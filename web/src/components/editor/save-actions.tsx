import {
	HeaderButton,
	HeaderPrimaryButton,
} from "@/components/layout/subpage-header";

interface SaveActionsProps {
	isDirty: boolean;
	isSaving: boolean;
	/** Extra validity gate on top of dirtiness (required fields, valid schedule…). */
	canSave?: boolean;
	onSave: () => void;
	onCancel?: () => void;
	saveLabel?: string;
}

/** Explicit-save button pair: optional Cancel + primary petrol Save. */
export function SaveActions({
	isDirty,
	isSaving,
	canSave = true,
	onSave,
	onCancel,
	saveLabel = "Save changes",
}: SaveActionsProps) {
	return (
		<>
			{onCancel && (
				<HeaderButton
					onClick={() => {
						onCancel();
					}}
					disabled={isSaving}
				>
					Cancel
				</HeaderButton>
			)}
			<HeaderPrimaryButton
				onClick={() => {
					onSave();
				}}
				disabled={!isDirty || !canSave || isSaving}
			>
				{isSaving ? "Saving…" : saveLabel}
			</HeaderPrimaryButton>
		</>
	);
}
