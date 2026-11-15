"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";

export const LONG_PRESS_DELAY_MS = 450;
export const LONG_PRESS_MOVE_TOLERANCE_PX = 10;
// The click a browser may synthesize when the finger lifts after a long press.
const CLICK_SUPPRESSION_MS = 700;

/** Disables the iOS link callout and text selection, which compete with the
 * gesture, on touch screens only. */
export const LONG_PRESS_TARGET_CLASS =
	"[-webkit-touch-callout:none] pointer-coarse:select-none";

interface PendingPress {
	timer: ReturnType<typeof setTimeout>;
	x: number;
	y: number;
	pointerId: number;
	onLongPress: () => void;
}

const NESTED_CONTROL_SELECTOR =
	'a[href], button, input, select, textarea, label, [role="button"], [role="checkbox"], [role="switch"], [role="menuitem"], [contenteditable="true"]';

/** A press that begins on a control inside the target (its checkbox, a menu
 * trigger, a switch) belongs to that control, not to the row. */
function startsOnNestedControl(event: React.PointerEvent): boolean {
	if (!(event.target instanceof Element)) return false;
	const control = event.target.closest(NESTED_CONTROL_SELECTOR);
	return (
		!!control &&
		control !== event.currentTarget &&
		event.currentTarget.contains(control)
	);
}

export interface LongPressHandlers {
	onPointerDown: (event: React.PointerEvent) => void;
	onPointerMove: (event: React.PointerEvent) => void;
	onPointerUp: () => void;
	onPointerCancel: () => void;
	onContextMenu: (event: React.MouseEvent) => void;
}

/**
 * Touch-only long press. `bind(callback)` returns the handlers for one target
 * (an empty object when `callback` is undefined, so ineligible targets keep
 * their native behaviour). `onClickCapture` belongs on the target or on an
 * ancestor that survives a re-render: it swallows the click released by the
 * same finger, even when the pressed element was swapped meanwhile.
 *
 * Mouse and pen are ignored, a finger that moves past the tolerance (or a
 * scroll, which the browser reports as `pointercancel`) abandons the press.
 */
export function useLongPress() {
	const pending = useRef<PendingPress | null>(null);
	const fired = useRef(false);
	const suppressClickUntil = useRef(0);
	const detachRelease = useRef<(() => void) | null>(null);

	const cancel = useCallback(() => {
		if (!pending.current) return;
		clearTimeout(pending.current.timer);
		pending.current = null;
	}, []);

	useEffect(
		() => () => {
			cancel();
			detachRelease.current?.();
		},
		[cancel],
	);

	const fire = useCallback(() => {
		const press = pending.current;
		if (!press) return;
		clearTimeout(press.timer);
		pending.current = null;
		fired.current = true;
		suppressClickUntil.current = Number.POSITIVE_INFINITY;
		// Listened on window: selecting may re-render the pressed row into a
		// different element, which then never sees the finger lift.
		detachRelease.current?.();
		const release = () => {
			detachRelease.current?.();
			fired.current = false;
			suppressClickUntil.current = Date.now() + CLICK_SUPPRESSION_MS;
		};
		window.addEventListener("pointerup", release, true);
		window.addEventListener("pointercancel", release, true);
		detachRelease.current = () => {
			window.removeEventListener("pointerup", release, true);
			window.removeEventListener("pointercancel", release, true);
			detachRelease.current = null;
		};
		if (typeof navigator !== "undefined" && "vibrate" in navigator) {
			try {
				navigator.vibrate(10);
			} catch {
				// Haptics are a nicety, never a requirement.
			}
		}
		press.onLongPress();
	}, []);

	const onClickCapture = useCallback((event: React.MouseEvent) => {
		if (Date.now() >= suppressClickUntil.current) return;
		suppressClickUntil.current = 0;
		event.preventDefault();
		event.stopPropagation();
	}, []);

	const bind = useCallback(
		(onLongPress: (() => void) | undefined): Partial<LongPressHandlers> => {
			if (!onLongPress) return {};
			return {
				onPointerDown: (event) => {
					if (event.pointerType !== "touch" || !event.isPrimary) return;
					if (startsOnNestedControl(event)) return;
					cancel();
					fired.current = false;
					suppressClickUntil.current = 0;
					pending.current = {
						timer: setTimeout(fire, LONG_PRESS_DELAY_MS),
						x: event.clientX,
						y: event.clientY,
						pointerId: event.pointerId,
						onLongPress,
					};
				},
				onPointerMove: (event) => {
					const press = pending.current;
					if (!press || press.pointerId !== event.pointerId) return;
					const distance = Math.hypot(
						event.clientX - press.x,
						event.clientY - press.y,
					);
					if (distance > LONG_PRESS_MOVE_TOLERANCE_PX) cancel();
				},
				onPointerUp: cancel,
				onPointerCancel: cancel,
				onContextMenu: (event) => {
					// Android raises its context menu at its own long-press
					// threshold, sometimes before ours: treat it as the gesture.
					if (pending.current) {
						event.preventDefault();
						fire();
					} else if (fired.current) {
						event.preventDefault();
					}
				},
			};
		},
		[cancel, fire],
	);

	return useMemo(() => ({ bind, onClickCapture }), [bind, onClickCapture]);
}
