import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useRowSelection } from "@/hooks/use-row-selection";
import {
	LONG_PRESS_DELAY_MS,
	LONG_PRESS_MOVE_TOLERANCE_PX,
} from "@/hooks/use-long-press";
import { DataTable, type DataTableColumn } from "./data-table";

interface Row {
	id: string;
	name: string;
	locked?: boolean;
}

const rows: Row[] = [
	{ id: "a", name: "Alpha" },
	{ id: "b", name: "Bravo" },
	{ id: "c", name: "Locked", locked: true },
];

const columns: DataTableColumn<Row>[] = [
	{ key: "name", header: "Name", cell: (row) => row.name },
	{
		key: "actions",
		header: "",
		cell: (row) => <button type="button">Menu {row.name}</button>,
	},
];

function Harness({
	onOpen,
	selectable = true,
}: {
	onOpen: (row: Row) => void;
	selectable?: boolean;
}) {
	const selection = useRowSelection({
		orderedIds: rows.map((row) => row.id),
		eligibleIds: rows.filter((row) => !row.locked).map((row) => row.id),
	});
	return (
		<>
			<output data-testid="count">{selection.selectedCount}</output>
			<DataTable
				columns={columns}
				rows={rows}
				rowKey={(row) => row.id}
				onRowClick={onOpen}
				isRowSelected={(row) => selection.isSelected(row.id)}
				selectionMode={selection.selectionMode}
				isRowSelectable={(row) => !row.locked}
				onRowSelectionClick={
					selectable
						? (row, shiftKey) => {
								selection.toggle(row.id, shiftKey);
							}
						: undefined
				}
			/>
		</>
	);
}

function row(name: string): HTMLElement {
	const element = screen.getByText(name).closest<HTMLElement>(".grid");
	if (!element) throw new Error(`Missing row ${name}`);
	return element;
}

const touch = { pointerType: "touch", isPrimary: true, pointerId: 1 };

function press(target: HTMLElement, init: Partial<PointerEventInit> = {}) {
	fireEvent.pointerDown(target, { ...touch, clientX: 50, clientY: 50, ...init });
}

/** Lift the finger, then let the browser deliver its synthetic click. */
function release(target: HTMLElement): boolean {
	fireEvent.pointerUp(target, { ...touch, clientX: 50, clientY: 50 });
	return fireEvent.click(target);
}

function count(): string {
	return screen.getByTestId("count").textContent ?? "";
}

describe("DataTable long press selection", () => {
	beforeEach(() => {
		vi.useFakeTimers();
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	it("selects the row, enters selection mode and swallows the release click", () => {
		const onOpen = vi.fn();
		render(<Harness onOpen={onOpen} />);

		const target = row("Alpha");
		press(target);
		act(() => {
			vi.advanceTimersByTime(LONG_PRESS_DELAY_MS);
		});

		expect(count()).toBe("1");
		expect(row("Alpha")).toHaveAttribute("data-selected", "true");
		// Selection mode swaps the open-on-click row for a toggle-on-click one.
		expect(row("Alpha")).not.toHaveAttribute("role", "button");

		const clickNotCancelled = release(row("Alpha"));
		expect(clickNotCancelled).toBe(false);
		expect(onOpen).not.toHaveBeenCalled();
		expect(count()).toBe("1");
	});

	it("keeps a short tap as a normal open", () => {
		const onOpen = vi.fn();
		render(<Harness onOpen={onOpen} />);

		const target = row("Alpha");
		press(target);
		act(() => {
			vi.advanceTimersByTime(LONG_PRESS_DELAY_MS - 100);
		});
		expect(release(target)).toBe(true);

		act(() => {
			vi.advanceTimersByTime(LONG_PRESS_DELAY_MS);
		});
		expect(onOpen).toHaveBeenCalledTimes(1);
		expect(count()).toBe("0");
	});

	it("abandons the press when the finger moves past the tolerance", () => {
		const onOpen = vi.fn();
		render(<Harness onOpen={onOpen} />);

		const target = row("Alpha");
		press(target);
		fireEvent.pointerMove(target, {
			...touch,
			clientX: 50,
			clientY: 50 + LONG_PRESS_MOVE_TOLERANCE_PX + 1,
		});
		act(() => {
			vi.advanceTimersByTime(LONG_PRESS_DELAY_MS * 2);
		});

		expect(count()).toBe("0");
	});

	it("tolerates a small finger jitter", () => {
		render(<Harness onOpen={vi.fn()} />);

		const target = row("Alpha");
		press(target);
		fireEvent.pointerMove(target, { ...touch, clientX: 53, clientY: 54 });
		act(() => {
			vi.advanceTimersByTime(LONG_PRESS_DELAY_MS);
		});

		expect(count()).toBe("1");
	});

	it("abandons the press when the browser takes over to scroll", () => {
		render(<Harness onOpen={vi.fn()} />);

		const target = row("Alpha");
		press(target);
		fireEvent.pointerCancel(target, touch);
		act(() => {
			vi.advanceTimersByTime(LONG_PRESS_DELAY_MS * 2);
		});

		expect(count()).toBe("0");
	});

	it("ignores a held mouse button", () => {
		const onOpen = vi.fn();
		render(<Harness onOpen={onOpen} />);

		const target = row("Alpha");
		press(target, { pointerType: "mouse" });
		act(() => {
			vi.advanceTimersByTime(LONG_PRESS_DELAY_MS * 2);
		});
		expect(release(target)).toBe(true);

		expect(count()).toBe("0");
		expect(onOpen).toHaveBeenCalledTimes(1);
	});

	it("leaves rows that cannot be selected alone", () => {
		const onOpen = vi.fn();
		render(<Harness onOpen={onOpen} />);

		const target = row("Locked");
		press(target);
		act(() => {
			vi.advanceTimersByTime(LONG_PRESS_DELAY_MS);
		});
		expect(release(target)).toBe(true);

		expect(count()).toBe("0");
		expect(onOpen).toHaveBeenCalledTimes(1);
	});

	it("does nothing on a list without selection", () => {
		const onOpen = vi.fn();
		render(<Harness onOpen={onOpen} selectable={false} />);

		const target = row("Alpha");
		const contextMenu = fireEvent.contextMenu(target);
		press(target);
		act(() => {
			vi.advanceTimersByTime(LONG_PRESS_DELAY_MS);
		});
		expect(release(target)).toBe(true);

		expect(contextMenu).toBe(true);
		expect(count()).toBe("0");
		expect(onOpen).toHaveBeenCalledTimes(1);
	});

	it("leaves a press on a nested control to that control", () => {
		render(<Harness onOpen={vi.fn()} />);

		press(screen.getByRole("button", { name: "Menu Alpha" }));
		act(() => {
			vi.advanceTimersByTime(LONG_PRESS_DELAY_MS);
		});

		expect(count()).toBe("0");
	});

	it("adds rows with further long presses and deselects with a tap", () => {
		render(<Harness onOpen={vi.fn()} />);

		press(row("Alpha"));
		act(() => {
			vi.advanceTimersByTime(LONG_PRESS_DELAY_MS);
		});
		release(row("Alpha"));
		act(() => {
			vi.advanceTimersByTime(1000);
		});

		press(row("Bravo"));
		act(() => {
			vi.advanceTimersByTime(LONG_PRESS_DELAY_MS);
		});
		release(row("Bravo"));
		expect(count()).toBe("2");

		// A long press on an already selected row keeps it selected.
		press(row("Alpha"));
		act(() => {
			vi.advanceTimersByTime(LONG_PRESS_DELAY_MS);
		});
		release(row("Alpha"));
		expect(count()).toBe("2");

		press(row("Alpha"));
		expect(release(row("Alpha"))).toBe(true);
		expect(row("Alpha")).not.toHaveAttribute("data-selected");
		expect(count()).toBe("1");
	});

	it("treats Android's context menu as the gesture and suppresses the menu", () => {
		render(<Harness onOpen={vi.fn()} />);

		const target = row("Alpha");
		press(target);
		act(() => {
			vi.advanceTimersByTime(LONG_PRESS_DELAY_MS - 100);
		});
		const notCancelled = fireEvent.contextMenu(target);

		expect(notCancelled).toBe(false);
		expect(count()).toBe("1");
	});

	it("does not follow a link row once it turned into a selected row", () => {
		function LinkHarness() {
			const selection = useRowSelection({ orderedIds: ["a"] });
			return (
				<DataTable
					columns={columns.slice(0, 1)}
					rows={rows.slice(0, 1)}
					rowKey={(item) => item.id}
					getRowHref={(item) => `/items/${item.id}`}
					isRowSelected={(item) => selection.isSelected(item.id)}
					selectionMode={selection.selectionMode}
					onRowSelectionClick={(item, shiftKey) => {
						selection.toggle(item.id, shiftKey);
					}}
				/>
			);
		}
		render(<LinkHarness />);

		const link = screen.getByRole("link");
		press(link);
		act(() => {
			vi.advanceTimersByTime(LONG_PRESS_DELAY_MS);
		});

		expect(screen.queryByRole("link")).toBeNull();
		const selectedRow = row("Alpha");
		expect(selectedRow).toHaveAttribute("data-selected", "true");
		expect(release(selectedRow)).toBe(false);
		expect(row("Alpha")).toHaveAttribute("data-selected", "true");
	});

	it("keeps the desktop right click menu", () => {
		render(<Harness onOpen={vi.fn()} />);

		expect(fireEvent.contextMenu(row("Alpha"))).toBe(true);
		expect(count()).toBe("0");
	});
});
