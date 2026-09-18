/** Compact "updated" time for library rows: just now, 5m ago, 2h ago, 3d ago, else a date. */
export function relativeTime(dateStr: string, now = Date.now()): string {
	const seconds = Math.floor((now - new Date(dateStr).getTime()) / 1000);
	if (seconds < 60) return "just now";
	const minutes = Math.floor(seconds / 60);
	if (minutes < 60) return `${minutes}m ago`;
	const hours = Math.floor(minutes / 60);
	if (hours < 24) return `${hours}h ago`;
	const days = Math.floor(hours / 24);
	if (days < 30) return `${days}d ago`;
	return new Date(dateStr).toLocaleDateString(undefined, {
		month: "short",
		day: "numeric",
	});
}
