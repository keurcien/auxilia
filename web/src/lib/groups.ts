export interface GroupedResource {
	group?: string | null;
}

export interface GroupNode<T> {
	name: string;
	path: string;
	depth: number;
	items: T[];
	children: GroupNode<T>[];
	count: number;
}

interface MutableGroupNode<T> extends Omit<GroupNode<T>, "children"> {
	children: Map<string, MutableGroupNode<T>>;
}

export interface GroupTree<T> {
	groups: GroupNode<T>[];
	ungrouped: T[];
}

export function flattenGroupTree<T>(tree: GroupTree<T>): T[] {
	const flattenNode = (node: GroupNode<T>): T[] => [
		...node.items,
		...node.children.flatMap(flattenNode),
	];
	return [...tree.groups.flatMap(flattenNode), ...tree.ungrouped];
}

export const normalizeGroup = (value: string): string =>
	value
		.split("/")
		.map((part) => part.trim())
		.filter(Boolean)
		.join("/");

export function groupOptions(resources: GroupedResource[]): string[] {
	return [
		...new Set(
			resources
				.map((resource) => resource.group)
				.filter((group): group is string => Boolean(group))
				.flatMap((group) => {
					const parts = group.split("/");
					return parts.map((_, index) => parts.slice(0, index + 1).join("/"));
				}),
		),
	].sort((a, b) => a.localeCompare(b));
}

const finalize = <T>(node: MutableGroupNode<T>): GroupNode<T> => {
	const children = [...node.children.values()]
		.sort((a, b) => a.name.localeCompare(b.name))
		.map(finalize);
	return {
		...node,
		children,
		count:
			node.items.length +
			children.reduce((total, child) => total + child.count, 0),
	};
};

export function buildGroupTree<T extends GroupedResource>(
	resources: T[],
): GroupTree<T> {
	const roots = new Map<string, MutableGroupNode<T>>();
	const ungrouped: T[] = [];

	for (const resource of resources) {
		const parts = resource.group
			?.split("/")
			.map((part) => part.trim())
			.filter(Boolean);
		if (!parts?.length) {
			ungrouped.push(resource);
			continue;
		}

		let siblings = roots;
		let path = "";
		parts.forEach((part, depth) => {
			path = path ? `${path}/${part}` : part;
			let node = siblings.get(part);
			if (!node) {
				node = {
					name: part,
					path,
					depth,
					items: [],
					children: new Map(),
					count: 0,
				};
				siblings.set(part, node);
			}
			if (depth === parts.length - 1) node.items.push(resource);
			siblings = node.children;
		});
	}

	return {
		groups: [...roots.values()]
			.sort((a, b) => a.name.localeCompare(b.name))
			.map(finalize),
		ungrouped,
	};
}
