"use client";

import { useMemo, useState } from "react";
import type { GanttTask, GanttEpic } from "@/components/gantt";
import { KanbanCard } from "./kanban-card";

const COLUMNS: { status: string; label: string }[] = [
  { status: "open", label: "Open" },
  { status: "in_review", label: "In Review" },
  { status: "done", label: "Done" },
];

interface KanbanBoardProps {
  tasks: GanttTask[];
  epics: GanttEpic[];
  onStatusChange: (taskId: string, status: string) => void;
  onTaskClick: (taskId: string) => void;
  filterAssignee?: string;
  filterEpic?: string;
  filterStatus?: string;
  filterPriority?: string;
}

export function KanbanBoard({
  tasks,
  epics,
  onStatusChange,
  onTaskClick,
  filterAssignee,
  filterEpic,
  filterStatus,
  filterPriority,
}: KanbanBoardProps) {
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [dragOverStatus, setDragOverStatus] = useState<string | null>(null);

  const filtered = useMemo(() => {
    let result = tasks;
    if (filterAssignee) result = result.filter((t) => t.assignee === filterAssignee);
    if (filterEpic) result = result.filter((t) => t.epic_id === filterEpic);
    if (filterStatus) result = result.filter((t) => t.status === filterStatus);
    if (filterPriority) result = result.filter((t) => t.priority === filterPriority);
    return result;
  }, [tasks, filterAssignee, filterEpic, filterStatus, filterPriority]);

  const epicMap = useMemo(() => {
    const map = new Map<string, GanttEpic>();
    for (const e of epics) map.set(e.id, e);
    return map;
  }, [epics]);

  const columns = useMemo(() => {
    return COLUMNS.map((col) => ({
      ...col,
      tasks: filtered.filter((t) => t.status === col.status),
    }));
  }, [filtered]);

  const handleDrop = (status: string) => {
    if (draggingId) {
      const task = filtered.find((t) => t.id === draggingId);
      if (task && task.status !== status) {
        onStatusChange(draggingId, status);
      }
    }
    setDraggingId(null);
    setDragOverStatus(null);
  };

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      {columns.map((col) => (
        <div
          key={col.status}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOverStatus(col.status);
          }}
          onDragLeave={() => setDragOverStatus((prev) => (prev === col.status ? null : prev))}
          onDrop={(e) => {
            e.preventDefault();
            handleDrop(col.status);
          }}
          className={`flex flex-col gap-2 rounded-lg border border-border bg-muted/20 p-3 transition-colors ${
            dragOverStatus === col.status ? "border-blue-400 bg-blue-500/5" : ""
          }`}
        >
          <div className="flex items-center justify-between px-1">
            <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {col.label}
            </h3>
            <span className="text-xs text-muted-foreground">{col.tasks.length}</span>
          </div>

          <div className="flex min-h-[80px] max-h-[560px] flex-col gap-2 overflow-y-auto pr-1">
            {col.tasks.map((task) => (
              <KanbanCard
                key={task.id}
                task={task}
                epicTitle={epicMap.get(task.epic_id)?.title}
                isDragging={draggingId === task.id}
                onDragStart={(e) => {
                  setDraggingId(task.id);
                  e.dataTransfer.effectAllowed = "move";
                }}
                onDragEnd={() => {
                  setDraggingId(null);
                  setDragOverStatus(null);
                }}
                onClick={() => onTaskClick(task.id)}
              />
            ))}
            {col.tasks.length === 0 && (
              <div className="flex flex-1 items-center justify-center rounded-md border border-dashed border-border/60 py-6 text-xs text-muted-foreground">
                No tasks
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
