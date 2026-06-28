"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import type { GanttTask, GanttEpic, ScheduleChange } from "./gantt-types";
import {
  addDays,
  diffDays,
  formatDate,
  formatShortDate,
  parseDate,
  startOfWeek,
  type ZoomLevel,
  getColumnWidth,
} from "./gantt-utils";
import { GanttBar } from "./gantt-bar";

const ROW_HEIGHT = 44;
const LABEL_WIDTH = 180;
const HEADER_HEIGHT = 52;

interface GanttChartProps {
  tasks: GanttTask[];
  epics: GanttEpic[];
  onScheduleChange: (change: ScheduleChange) => void;
  onTaskClick: (taskId: string) => void;
  zoom: ZoomLevel;
  filterAssignee?: string;
  filterEpic?: string;
  filterStatus?: string;
  filterPriority?: string;
}

function getTimelineRange(tasks: GanttTask[]): { start: Date; end: Date } {
  const now = new Date();
  let earliest = now;
  let latest = addDays(now, 30);

  for (const task of tasks) {
    if (task.start_date) {
      const s = parseDate(task.start_date);
      if (s < earliest) earliest = s;
    }
    if (task.end_date) {
      const e = parseDate(task.end_date);
      if (e > latest) latest = e;
    }
  }

  const start = startOfWeek(addDays(earliest, -7));
  const end = addDays(latest, 14);
  return { start, end };
}

function generateDateColumns(start: Date, end: Date) {
  const cols: Date[] = [];
  let d = new Date(start);
  while (d <= end) {
    cols.push(new Date(d));
    d = addDays(d, 1);
  }
  return cols;
}

function generateWeekMarkers(start: Date, end: Date) {
  const markers: { date: Date; label: string }[] = [];
  let d = startOfWeek(start);
  while (d <= end) {
    markers.push({ date: new Date(d), label: formatShortDate(d) });
    d = addDays(d, 7);
  }
  return markers;
}

export function GanttChart({
  tasks,
  epics,
  onScheduleChange,
  onTaskClick,
  zoom,
  filterAssignee,
  filterEpic,
  filterStatus,
  filterPriority,
}: GanttChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [dragState, setDragState] = useState<{
    taskId: string;
    type: "move" | "resize";
    startX: number;
    origStart: Date;
    origEnd: Date;
  } | null>(null);
  const [dragOffsetDays, setDragOffsetDays] = useState(0);

  const filtered = useMemo(() => {
    let result = tasks;
    if (filterAssignee) result = result.filter((t) => t.assignee === filterAssignee);
    if (filterEpic) result = result.filter((t) => t.epic_id === filterEpic);
    if (filterStatus) result = result.filter((t) => t.status === filterStatus);
    if (filterPriority) result = result.filter((t) => t.priority === filterPriority);
    return result;
  }, [tasks, filterAssignee, filterEpic, filterStatus, filterPriority]);

  const assignees = useMemo(() => {
    const set = new Set<string>();
    for (const t of filtered) {
      set.add(t.assignee ?? "Unassigned");
    }
    const sorted = Array.from(set).sort();
    const unIdx = sorted.indexOf("Unassigned");
    if (unIdx > -1) {
      sorted.splice(unIdx, 1);
      sorted.push("Unassigned");
    }
    return sorted;
  }, [filtered]);

  const rows = useMemo(() => {
    const map = new Map<string, GanttTask[]>();
    for (const a of assignees) map.set(a, []);
    for (const t of filtered) {
      const key = t.assignee ?? "Unassigned";
      map.get(key)?.push(t);
    }
    return assignees.map((a) => ({ assignee: a, tasks: map.get(a) ?? [] }));
  }, [filtered, assignees]);

  const { start: timelineStart, end: timelineEnd } = useMemo(
    () => getTimelineRange(filtered),
    [filtered],
  );

  const dateCols = useMemo(
    () => generateDateColumns(timelineStart, timelineEnd),
    [timelineStart, timelineEnd],
  );

  const weekMarkers = useMemo(
    () => generateWeekMarkers(timelineStart, timelineEnd),
    [timelineStart, timelineEnd],
  );

  const colWidth = getColumnWidth(zoom);
  const totalWidth = dateCols.length * colWidth;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const todayOffset = diffDays(timelineStart, today) * colWidth;

  const getBarPosition = useCallback(
    (task: GanttTask) => {
      const taskStart = task.start_date ? parseDate(task.start_date) : new Date();
      const days = task.estimated_days ?? 5;
      const taskEnd = task.end_date ? parseDate(task.end_date) : addDays(taskStart, days);

      const left = diffDays(timelineStart, taskStart) * colWidth;
      const width = Math.max(diffDays(taskStart, taskEnd) * colWidth, colWidth);
      return { left, width };
    },
    [timelineStart, colWidth],
  );

  const handleMouseDown = useCallback(
    (taskId: string, type: "move" | "resize", e: React.MouseEvent) => {
      e.preventDefault();
      e.stopPropagation();
      const task = filtered.find((t) => t.id === taskId);
      if (!task) return;

      const taskStart = task.start_date ? parseDate(task.start_date) : new Date();
      const days = task.estimated_days ?? 5;
      const taskEnd = task.end_date ? parseDate(task.end_date) : addDays(taskStart, days);

      setDragState({ taskId, type, startX: e.clientX, origStart: taskStart, origEnd: taskEnd });
      setDragOffsetDays(0);
    },
    [filtered],
  );

  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      if (!dragState) return;
      const dx = e.clientX - dragState.startX;
      const daysDelta = Math.round(dx / colWidth);
      setDragOffsetDays(daysDelta);
    },
    [dragState, colWidth],
  );

  const handleMouseUp = useCallback(() => {
    if (!dragState || dragOffsetDays === 0) {
      setDragState(null);
      setDragOffsetDays(0);
      return;
    }

    let newStart: Date;
    let newEnd: Date;

    if (dragState.type === "move") {
      newStart = addDays(dragState.origStart, dragOffsetDays);
      newEnd = addDays(dragState.origEnd, dragOffsetDays);
    } else {
      newStart = dragState.origStart;
      newEnd = addDays(dragState.origEnd, dragOffsetDays);
      if (newEnd <= newStart) newEnd = addDays(newStart, 1);
    }

    onScheduleChange({
      taskId: dragState.taskId,
      start_date: formatDate(newStart),
      end_date: formatDate(newEnd),
    });

    setDragState(null);
    setDragOffsetDays(0);
  }, [dragState, dragOffsetDays, onScheduleChange]);

  const getDragAdjustedPosition = useCallback(
    (task: GanttTask) => {
      const pos = getBarPosition(task);
      if (!dragState || dragState.taskId !== task.id) return pos;

      if (dragState.type === "move") {
        return { left: pos.left + dragOffsetDays * colWidth, width: pos.width };
      } else {
        const newWidth = pos.width + dragOffsetDays * colWidth;
        return { left: pos.left, width: Math.max(newWidth, colWidth) };
      }
    },
    [getBarPosition, dragState, dragOffsetDays, colWidth],
  );

  const epicMap = useMemo(() => {
    const map = new Map<string, GanttEpic>();
    for (const e of epics) map.set(e.id, e);
    return map;
  }, [epics]);

  return (
    <div
      ref={containerRef}
      className="relative overflow-auto rounded-lg border border-border bg-card"
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
    >
      <div className="flex" style={{ minWidth: LABEL_WIDTH + totalWidth }}>
        {/* Left labels column */}
        <div
          className="sticky left-0 z-20 border-r border-border bg-card"
          style={{ width: LABEL_WIDTH, minWidth: LABEL_WIDTH }}
        >
          {/* Header */}
          <div
            className="flex items-end border-b border-border px-3 pb-2 text-xs font-medium text-muted-foreground"
            style={{ height: HEADER_HEIGHT }}
          >
            Assignee
          </div>

          {/* Row labels */}
          {rows.map((row) => (
            <div
              key={row.assignee}
              className="flex items-center border-b border-border/50 px-3 text-sm font-medium"
              style={{ height: ROW_HEIGHT * Math.max(row.tasks.length, 1) }}
            >
              <span className="truncate">{row.assignee}</span>
            </div>
          ))}
        </div>

        {/* Timeline area */}
        <div className="relative flex-1" style={{ width: totalWidth }}>
          {/* Timeline header */}
          <div className="sticky top-0 z-10 border-b border-border bg-card" style={{ height: HEADER_HEIGHT }}>
            <div className="relative h-full">
              {weekMarkers.map((marker) => {
                const x = diffDays(timelineStart, marker.date) * colWidth;
                return (
                  <div
                    key={marker.label}
                    className="absolute bottom-2 text-xs text-muted-foreground"
                    style={{ left: x }}
                  >
                    {marker.label}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Grid background */}
          <div className="absolute inset-0" style={{ top: HEADER_HEIGHT }}>
            {dateCols.map((d, i) => {
              const isWeekend = d.getDay() === 0 || d.getDay() === 6;
              return (
                <div
                  key={i}
                  className={`absolute top-0 bottom-0 border-r border-border/20 ${
                    isWeekend ? "bg-muted/30" : ""
                  }`}
                  style={{ left: i * colWidth, width: colWidth }}
                />
              );
            })}

            {/* Today line */}
            {todayOffset >= 0 && todayOffset <= totalWidth && (
              <div
                className="absolute top-0 bottom-0 z-10 w-0.5 bg-blue-500"
                style={{ left: todayOffset }}
              />
            )}
          </div>

          {/* Task rows */}
          <div className="relative" style={{ top: 0 }}>
            {rows.map((row) => (
              <div
                key={row.assignee}
                className="relative border-b border-border/50"
                style={{ height: ROW_HEIGHT * Math.max(row.tasks.length, 1) }}
              >
                {row.tasks.map((task, taskIdx) => {
                  const pos = getDragAdjustedPosition(task);
                  const epic = epicMap.get(task.epic_id);
                  const isDragging = dragState?.taskId === task.id;
                  return (
                    <GanttBar
                      key={task.id}
                      task={task}
                      epicTitle={epic?.title}
                      left={pos.left}
                      width={pos.width}
                      top={taskIdx * ROW_HEIGHT + 6}
                      isDragging={isDragging}
                      onMouseDownMove={(e) => handleMouseDown(task.id, "move", e)}
                      onMouseDownResize={(e) => handleMouseDown(task.id, "resize", e)}
                      onClick={() => onTaskClick(task.id)}
                    />
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      </div>

      {rows.length === 0 && (
        <div className="flex items-center justify-center py-16 text-sm text-muted-foreground">
          No tasks match the current filters
        </div>
      )}
    </div>
  );
}
