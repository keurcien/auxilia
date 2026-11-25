const fold = (value: string) =>
	value
		.normalize("NFD")
		.replace(/\p{Diacritic}/gu, "")
		.toLowerCase();

/** Case- and accent-insensitive: every word of the query must appear in one of the fields. */
export function matchesQuery(
	query: string,
	...fields: (string | null | undefined)[]
): boolean {
	const terms = fold(query).split(/\s+/).filter(Boolean);
	if (terms.length === 0) return true;
	const haystack = fold(fields.filter(Boolean).join(" "));
	return terms.every((term) => haystack.includes(term));
}
