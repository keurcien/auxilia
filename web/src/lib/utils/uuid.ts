/**
 * RFC 4122 v4 UUID that also works outside secure contexts.
 *
 * `crypto.randomUUID()` is only exposed on secure origins (HTTPS or
 * localhost); a self-hosted auxilia served over plain HTTP on a LAN
 * address doesn't have it, and thread creation must not depend on it.
 * `crypto.getRandomValues` is available everywhere.
 */
export function generateUuid(): string {
	// The DOM types declare randomUUID unconditionally; at runtime it is
	// absent on insecure origins — widen so the check is meaningful.
	const c = crypto as Crypto & { randomUUID?: () => string };
	if (typeof c.randomUUID === "function") return c.randomUUID();

	const bytes = new Uint8Array(16);
	crypto.getRandomValues(bytes);
	bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
	bytes[8] = (bytes[8] & 0x3f) | 0x80; // RFC 4122 variant
	const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
	return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
