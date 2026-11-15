import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LONG_PRESS_DELAY_MS } from "@/hooks/use-long-press";
import type { Trigger } from "@/types/triggers";
import TriggerCard from "./trigger-card";

const push = vi.fn();

vi.mock("next/navigation", () => ({
	useRouter: () => ({ push }),
}));

function trigger(overrides: Partial<Trigger> = {}): Trigger {
	return {
		id: "t1",
		name: "Morning digest",
		triggerType: "webhook",
		instructions: "Summarize",
		agentId: "agent-1",
		modelId: "model-1",
		modelAvailable: true,
		isActive: true,
		runOnce: false,
		visibility: "workspace",
		teamIds: [],
		canManage: true,
		...overrides,
	} as Trigger;
}

function Harness({ item }: { item: Trigger }) {
	const [selected, setSelected] = useState(false);
	return (
		<TriggerCard
			trigger={item}
			onDelete={vi.fn()}
			onDuplicate={vi.fn()}
			canCreate
			selected={selected}
			selectionMode={selected}
			onToggleSelection={() => {
				setSelected((current) => !current);
			}}
		/>
	);
}

const touch = { pointerType: "touch", isPrimary: true, pointerId: 1 };

function card(): HTMLElement {
	const element = screen.getByText("Morning digest").closest<HTMLElement>(".rounded-2xl");
	if (!element) throw new Error("Missing card");
	return element;
}

describe("TriggerCard long press", () => {
	beforeEach(() => {
		vi.useFakeTimers();
		push.mockReset();
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	it("selects on a long press without opening the trigger, then deselects on tap", () => {
		render(<Harness item={trigger()} />);

		fireEvent.pointerDown(card(), { ...touch, clientX: 10, clientY: 10 });
		act(() => {
			vi.advanceTimersByTime(LONG_PRESS_DELAY_MS);
		});
		fireEvent.pointerUp(card(), touch);
		expect(fireEvent.click(card())).toBe(false);

		expect(push).not.toHaveBeenCalled();
		expect(screen.getByRole("checkbox", { name: "Select Morning digest" })).toBeChecked();

		fireEvent.pointerDown(card(), { ...touch, clientX: 10, clientY: 10 });
		fireEvent.pointerUp(card(), touch);
		fireEvent.click(card());

		expect(screen.getByRole("checkbox", { name: "Select Morning digest" })).not.toBeChecked();
		expect(push).not.toHaveBeenCalled();
	});

	it("opens on a short tap", () => {
		render(<Harness item={trigger()} />);

		fireEvent.pointerDown(card(), { ...touch, clientX: 10, clientY: 10 });
		fireEvent.pointerUp(card(), touch);
		fireEvent.click(card());

		expect(push).toHaveBeenCalledWith("/triggers/t1");
	});

	it("keeps a trigger the user cannot manage unselectable", () => {
		render(<Harness item={trigger({ canManage: false })} />);

		fireEvent.pointerDown(card(), { ...touch, clientX: 10, clientY: 10 });
		act(() => {
			vi.advanceTimersByTime(LONG_PRESS_DELAY_MS);
		});
		fireEvent.pointerUp(card(), touch);
		fireEvent.click(card());

		expect(screen.queryByRole("checkbox")).toBeNull();
		expect(push).toHaveBeenCalledWith("/triggers/t1");
	});
});
