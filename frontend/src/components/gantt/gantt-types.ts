export interface GanttTask {
  id: string;
  title: string;
  description?: string;
  status: string;
  priority: string;
  assignee: string | null;
  epic_id: string;
  start_date: string | null;
  end_date: string | null;
  estimated_days: number | null;
  dependencies: string[];
}

export interface GanttEpic {
  id: string;
  title: string;
}

export interface ScheduleChange {
  taskId: string;
  start_date: string;
  end_date: string;
  assignee?: string;
}
