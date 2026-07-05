export interface GithubIssueRef {
  id: string;
  number: number;
  title: string;
  state: string;
  html_url?: string | null;
}

export interface GithubPrRef {
  id: string;
  number: number;
  title: string;
  state: string;
  merged?: boolean;
  html_url?: string | null;
}

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
  github_issue?: GithubIssueRef | null;
  github_prs?: GithubPrRef[];
  github_conflict?: boolean;
  github_conflict_reason?: string | null;
  github_sync_error?: string | null;
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
