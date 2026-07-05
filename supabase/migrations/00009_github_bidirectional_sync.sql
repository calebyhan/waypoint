-- Bidirectional GitHub sync: canonical 1:1 task<->issue link, sync bookkeeping,
-- proposal dedup, and a retry outbox for writes going back to GitHub.
--
-- All current github_issues/github_prs/match_proposals rows are test data
-- (confirmed), so we reset rather than backfill.
truncate table public.match_proposals, public.github_prs, public.github_issues cascade;

-- Canonical, enforced 1:1 pointer from task -> its GitHub issue. PRs stay
-- many:1 on github_prs.linked_task_id (a revert PR or follow-up PR can
-- legitimately reference the same task); only issue linking must be strict 1:1.
alter table public.tasks
  add column github_issue_id uuid references public.github_issues(id) on delete set null,
  add column github_synced_at timestamptz,
  add column github_conflict boolean not null default false,
  add column github_conflict_reason text,
  add column github_sync_error text;

create unique index tasks_github_issue_id_unique on public.tasks(github_issue_id)
  where github_issue_id is not null;

-- github_issues.linked_task_id is retired as a writable link now that
-- tasks.github_issue_id is canonical.
alter table public.github_issues drop column linked_task_id;

alter table public.github_issues
  add column body text,
  add column html_url text,
  add column github_updated_at timestamptz,
  add column waypoint_updated_at timestamptz;

alter table public.github_prs
  add column html_url text,
  add column github_updated_at timestamptz;

-- Dedup guard for match_proposals: a plain composite unique constraint across
-- (task_id, github_issue_id, github_pr_id) would NOT dedupe, since Postgres
-- treats NULL columns as distinct in a unique index, and exactly one of
-- github_issue_id/github_pr_id is always NULL per proposal. Use two partial
-- unique indexes instead, one per proposal kind.
create unique index match_proposals_unique_issue
  on public.match_proposals(workspace_id, task_id, github_issue_id)
  where github_issue_id is not null and status = 'pending';

create unique index match_proposals_unique_pr
  on public.match_proposals(workspace_id, task_id, github_pr_id)
  where github_pr_id is not null and status = 'pending';

-- Retry outbox for GitHub write-back failures (rate limits, timeouts).
create table public.github_write_outbox (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  task_id uuid not null references public.tasks(id) on delete cascade,
  kind text not null check (kind in ('create_issue', 'update_issue', 'close_issue', 'reopen_issue')),
  payload jsonb not null,
  attempts integer not null default 0,
  last_error text,
  created_at timestamptz not null default now(),
  completed_at timestamptz
);

create index idx_github_write_outbox_pending on public.github_write_outbox(workspace_id) where completed_at is null;

alter table public.github_write_outbox enable row level security;

create policy "Members can read workspace outbox"
  on public.github_write_outbox for select
  using (workspace_id in (select workspace_id from public.workspace_members where user_id = auth.uid()));
