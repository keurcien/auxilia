/**
 * Share one in-flight load between concurrent callers.
 *
 * Stores use this so two components mounting before the first fetch resolves
 * fire one request, not two. `run()` joins the in-flight load if there is one;
 * `refresh()` always loads again, after the in-flight one settles so a stale
 * response cannot land on top of a fresh one.
 */
export function createOnce<T>(load: () => Promise<T>) {
	let inflight: Promise<T> | null = null;

	const track = (p: Promise<T>): Promise<T> => {
		inflight = p;
		p.then(
			() => {
				if (inflight === p) inflight = null;
			},
			() => {
				if (inflight === p) inflight = null;
			},
		);
		return p;
	};

	return {
		/** Start `load` unless one is already in flight; share that one. */
		run: (): Promise<T> => inflight ?? track(load()),
		/** Load again. If a load is in flight, run after it settles (either way). */
		refresh: (): Promise<T> => track(inflight ? inflight.then(load, load) : load()),
		/** Forget the in-flight load (tests). */
		reset: () => {
			inflight = null;
		},
	};
}
