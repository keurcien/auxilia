"use client";

import { cn } from "@/lib/utils";
import { memo } from "react";

interface Todo {
	status: "pending" | "in_progress" | "completed";
	content: string;
}

interface TodoProgressBarProps {
	todos: Todo[];
}

const TodoProgressBar = memo(({ todos }: TodoProgressBarProps) => {
	const completed = todos.filter((t) => t.status === "completed").length;
	const total = todos.length;
	const pct = total > 0 ? (completed / total) * 100 : 0;

	return (
		<div className="flex items-center gap-2 text-xs text-muted-foreground">
			<div className="h-1.5 flex-1 rounded-full bg-muted overflow-hidden">
				<div
					className="h-full rounded-full bg-primary transition-all duration-300"
					style={{ width: `${pct}%` }}
				/>
			</div>
			<span>
				{completed}/{total} tasks
			</span>
		</div>
	);
});

TodoProgressBar.displayName = "TodoProgressBar";

interface TodoItemProps {
	todo: Todo;
}

const TodoItem = memo(({ todo }: TodoItemProps) => {
	return (
		<div
			className={cn(
				"flex items-start gap-2 text-sm",
				todo.status === "completed" && "text-muted-foreground",
			)}
		>
			<span className="shrink-0 mt-0.5">
				{todo.status === "pending" && (
					<span className="text-muted-foreground">&#9675;</span>
				)}
				{todo.status === "in_progress" && (
					<span className="text-primary animate-pulse">&#9673;</span>
				)}
				{todo.status === "completed" && (
					<span className="text-emerald-500">&#10003;</span>
				)}
			</span>
			<span>{todo.content}</span>
		</div>
	);
});

TodoItem.displayName = "TodoItem";

interface TodoListProps {
	todos: Todo[];
	className?: string;
}

const TodoList = memo(({ todos, className }: TodoListProps) => {
	if (todos.length === 0) return null;

	return (
		<div className={cn("space-y-2", className)}>
			<TodoProgressBar todos={todos} />
			<div className="space-y-1">
				{todos.map((todo, index) => (
					<TodoItem key={index} todo={todo} />
				))}
			</div>
		</div>
	);
});

TodoList.displayName = "TodoList";

export { TodoList, TodoItem, TodoProgressBar };
export type { Todo };
