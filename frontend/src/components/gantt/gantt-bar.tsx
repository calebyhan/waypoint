"use client";

import type { GanttTask } from "./gantt-types";
import { PRIORITY_BAR_COLORS } from "@/lib/priority-colors";

const STATUS_PATTERNS: Record<string, string> = {
  done: "opacity-60",
  in_review: "ring-2 ring-blue-400/50",
  open: "",
};

interface GanttBarProps {
  task: GanttTask;
  epicTitle?: string;
  left: number;
  width: number;
  top: number;
  isDragging: boolean;
  onMouseDownMove: (e: React.MouseEvent) => void;
  onMouseDownResize: (e: React.MouseEvent) => void;
  onClick: () => void;
}

export function GanttBar({
  task,
  epicTitle,
  left,
  width,
  top,
  isDragging,
  onMouseDownMove,
  onMouseDownResize,
  onClick,
}: GanttBarProps) {
  const colorClass = PRIORITY_BAR_COLORS[task.priority] ?? PRIORITY_BAR_COLORS.p1;
  const statusClass = STATUS_PATTERNS[task.status] ?? "";

  // Known limitation: drag-to-move (onMouseDownMove) and drag-to-resize
  // (onMouseDownResize) are pointer-only interactions; a full keyboard
  // reschedule flow is out of scope. Enter/Space opens the task detail panel,
  // where dates can be edited with the keyboard.
  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={`${task.title}, priority ${task.priority}, status ${task.status}${epicTitle ? `, epic ${epicTitle}` : ""}`}
      className={`absolute flex items-center rounded-md text-white text-xs font-medium select-none ${colorClass} ${statusClass} ${
        isDragging ? "z-30 shadow-lg scale-[1.02]" : "z-10 shadow-sm"
      }`}
      style={{
        left,
        width,
        top,
        height: 32,
        cursor: isDragging ? "grabbing" : "grab",
        transition: isDragging ? "none" : "box-shadow 0.15s, transform 0.15s",
      }}
      onMouseDown={onMouseDownMove}
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick();
        }
      }}
      title={`${task.title}${epicTitle ? ` (${epicTitle})` : ""}`}
    >
      {/* Priority is also shown as text so it is not conveyed by color alone. */}
      <span className="truncate px-2">
        {task.priority.toUpperCase()} · {task.title}
      </span>

      {/* Resize handle — pointer-only affordance; the detail panel provides the accessible path. */}
      <div
        role="presentation"
        aria-hidden="true"
        className="absolute right-0 top-0 bottom-0 w-2 cursor-ew-resize hover:bg-white/20 rounded-r-md"
        onMouseDown={onMouseDownResize}
      />
    </div>
  );
}
