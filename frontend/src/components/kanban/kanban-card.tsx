"use client";

import { Badge } from "@/components/ui/badge";
import type { GanttTask } from "@/components/gantt";

const PRIORITY_COLORS: Record<string, string> = {
  p0: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  p1: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
  p2: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
};

interface KanbanCardProps {
  task: GanttTask;
  epicTitle?: string;
  isDragging: boolean;
  onDragStart: (e: React.DragEvent) => void;
  onDragEnd: () => void;
  onClick: () => void;
}

export function KanbanCard({
  task,
  epicTitle,
  isDragging,
  onDragStart,
  onDragEnd,
  onClick,
}: KanbanCardProps) {
  return (
    <div
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onClick={onClick}
      className={`cursor-grab space-y-2 rounded-lg border border-border bg-card p-3 shadow-sm transition-shadow hover:shadow-md active:cursor-grabbing ${
        isDragging ? "opacity-40" : ""
      }`}
    >
      <p className="text-sm font-medium leading-snug">{task.title}</p>
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge className={PRIORITY_COLORS[task.priority] ?? PRIORITY_COLORS.p1} variant="secondary">
          {task.priority.toUpperCase()}
        </Badge>
        {epicTitle && (
          <Badge variant="outline" className="max-w-[140px] truncate">
            {epicTitle}
          </Badge>
        )}
      </div>
      <p className="truncate text-xs text-muted-foreground">
        {task.assignee ?? "Unassigned"}
      </p>
    </div>
  );
}
