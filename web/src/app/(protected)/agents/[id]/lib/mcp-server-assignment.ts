export function shouldCloseAddToolDialogAfterServerAdded(
	availableServerIds: readonly string[],
	addedServerId: string,
): boolean {
	return availableServerIds.length === 1 && availableServerIds[0] === addedServerId;
}
