import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DataTable, type DataTableColumn } from "./data-table";

interface Row {
	id: string;
	name: string;
}

const columns: DataTableColumn<Row>[] = [
	{ key: "name", header: "Name", cell: (row) => row.name },
];
const rows: Row[] = Array.from({ length: 40 }, (_, index) => ({
	id: `row-${index}`,
	name: `Trigger ${index}`,
}));

function rowsContainer(name: string): HTMLElement {
	const container = screen.getByText(name).closest(".rounded-\\[10px\\]");
	if (!(container instanceof HTMLElement)) {
		throw new Error("Missing rows container");
	}
	return container;
}

describe("DataTable", () => {
	it("scrolls a long body in a positioned container", () => {
		render(
			<DataTable columns={columns} rows={rows} rowKey={(row) => row.id} scrollBody />,
		);

		expect(rowsContainer("Trigger 39")).toHaveClass(
			"relative",
			"min-h-0",
			"overflow-y-auto",
		);
	});

	it("keeps a non-scrolling body positioned", () => {
		render(<DataTable columns={columns} rows={rows} rowKey={(row) => row.id} />);

		const container = rowsContainer("Trigger 39");
		expect(container).toHaveClass("relative", "overflow-hidden");
		expect(container).not.toHaveClass("overflow-y-auto");
	});

	it("folds lg-only columns out of the mobile and md grids", () => {
		const { container } = render(
			<DataTable
				columns={[
					{ key: "name", header: "Name", width: "2fr", mobileWidth: "1fr", cell: (row) => row.name },
					{ key: "owner", header: "Owner", width: "1fr", hideBelowLg: true, cell: () => "Owner" },
					{ key: "created", header: "Created", width: "110px", mobileWidth: "auto", cell: () => "today" },
				]}
				rows={rows.slice(0, 1)}
				rowKey={(row) => row.id}
			/>,
		);

		const table = container.querySelector<HTMLElement>("[style*='--dt-cols']");
		expect(table?.style.getPropertyValue("--dt-cols")).toBe("1fr auto");
		expect(table?.style.getPropertyValue("--dt-cols-md")).toBe("2fr 110px");
		expect(table?.style.getPropertyValue("--dt-cols-lg")).toBe("2fr 1fr 110px");
		expect(screen.getByText("Owner", { selector: "div" })).toHaveClass(
			"hidden",
			"lg:block",
		);
	});
});
