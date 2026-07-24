"use client";

import { Badge } from "@/components/ui/badge";
import type { GanttTask } from "@/components/gantt";
import { PRIORITY_COLORS } from "@/lib/priority-colors";

function GithubBadge({ number, state, href }: { number: number; state: string; href?: string | null }) {
  const isOpen = state === "open";
  const badge = (
    <Badge
      variant="outline"
      className={isOpen ? "border-green-600/40 text-green-700 dark:text-green-400" : "border-purple-600/40 text-purple-700 dark:text-purple-400"}
    >
      #{number}
    </Badge>
  );
  if (!href) return badge;
  return (
    <a href={href} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
      {badge}
    </a>
  );
}

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
        {task.github_issue && (
          <GithubBadge
            number={task.github_issue.number}
            state={task.github_issue.state}
            href={task.github_issue.html_url}
          />
        )}
        {task.github_prs?.map((pr) => (
          <GithubBadge key={pr.id} number={pr.number} state={pr.merged ? "merged" : pr.state} href={pr.html_url} />
        ))}
      </div>
      <p className="truncate text-xs text-muted-foreground">
        {task.assignee ?? "Unassigned"}
      </p>
    </div>
  );
}
