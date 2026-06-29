create table public.team_members (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  name text not null,
  role text not null default 'fullstack' check (role in ('frontend', 'backend', 'fullstack', 'devops', 'design', 'qa', 'pm')),
  weekly_capacity_hours integer not null default 40,
  created_at timestamptz not null default now()
);

alter table public.team_members enable row level security;

create policy "Workspace members can read team members"
  on public.team_members for select
  using (
    workspace_id in (
      select workspace_id from public.workspace_members where user_id = auth.uid()
    )
  );

create policy "Workspace members can manage team members"
  on public.team_members for all
  using (
    workspace_id in (
      select workspace_id from public.workspace_members where user_id = auth.uid()
    )
  );

create index idx_team_members_workspace on public.team_members(workspace_id);
