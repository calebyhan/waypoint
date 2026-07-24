// Single source of truth for task-priority styling.
// Badge-style classes (background + text) used on dashboard, proposal, and kanban views.
export const PRIORITY_COLORS: Record<string, string> = {
  p0: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  p1: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
  p2: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
};

// Solid bar fills used by the Gantt chart's task bars.
export const PRIORITY_BAR_COLORS: Record<string, string> = {
  p0: "bg-red-500/80 hover:bg-red-500",
  p1: "bg-amber-500/80 hover:bg-amber-500",
  p2: "bg-slate-400/80 hover:bg-slate-400",
};
