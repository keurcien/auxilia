/**
 * Submit a message parked by the starter page once the thread has hydrated —
 * a submit before hydration lands would be reordered or dropped by the stream
 * stack. Hydration can hang (an unreachable snapshot), so a cap bounds the
 * wait. Exactly one submit either way.
 */
export async function submitPendingAfterHydration(
	hydration: Promise<unknown>,
	submit: () => void,
	{ capMs = 4_000 }: { capMs?: number } = {},
): Promise<void> {
	let timer: ReturnType<typeof setTimeout> | undefined;
	const settled = hydration.then(
		() => undefined,
		() => undefined,
	);
	const cap = new Promise<void>((resolve) => {
		timer = setTimeout(resolve, capMs);
	});
	try {
		await Promise.race([settled, cap]);
	} finally {
		clearTimeout(timer);
	}
	submit();
}
