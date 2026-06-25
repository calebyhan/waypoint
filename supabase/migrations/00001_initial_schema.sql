-- Enable pgvector extension for task embeddings
create extension if not exists vector with schema extensions;

-- Profiles (extends Supabase auth.users)
create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  github_username text not null,
  avatar_url text,
  gemini_api_key text,
  created_at timestamptz not null default now()
);

alter table public.profiles enable row level security;

create policy "Users can read own profile"
  on public.profiles for select
  using (auth.uid() = id);

create policy "Users can update own profile"
  on public.profiles for update
  using (auth.uid() = id);

-- Auto-create profile on signup
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = ''
as $$
begin
  insert into public.profiles (id, github_username, avatar_url)
  values (
    new.id,
    coalesce(new.raw_user_meta_data ->> 'user_name', new.raw_user_meta_data ->> 'preferred_username', ''),
    new.raw_user_meta_data ->> 'avatar_url'
  );
  return new;
end;
$$;

create or replace trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- Workspaces
create table public.workspaces (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  state text not null default 'active' check (state in ('active', 'archived', 'deleted')),
  owner_id uuid not null references public.profiles(id),
  repo_owner text,
  repo_name text,
  webhook_secret text,
  version integer not null default 1,
  created_at timestamptz not null default now()
);

alter table public.workspaces enable row level security;

-- Workspace members
create table public.workspace_members (
  workspace_id uuid references public.workspaces(id) on delete cascade,
  user_id uuid references public.profiles(id) on delete cascade,
  primary key (workspace_id, user_id)
);

alter table public.workspace_members enable row level security;

create policy "Members can read own memberships"
  on public.workspace_members for select
  using (auth.uid() = user_id);

create policy "Workspace owners can manage members"
  on public.workspace_members for all
  using (
    workspace_id in (
      select id from public.workspaces where owner_id = auth.uid()
    )
  );

create policy "Members can read their workspaces"
  on public.workspaces for select
  using (
    id in (
      select workspace_id from public.workspace_members where user_id = auth.uid()
    )
  );

create policy "Owners can update their workspaces"
  on public.workspaces for update
  using (owner_id = auth.uid());

create policy "Authenticated users can create workspaces"
  on public.workspaces for insert
  with check (auth.uid() = owner_id);

-- Epics
create table public.epics (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  title text not null,
  sort_order integer not null default 0,
  created_at timestamptz not null default now()
);

alter table public.epics enable row level security;

create policy "Workspace members can read epics"
  on public.epics for select
  using (
    workspace_id in (
      select workspace_id from public.workspace_members where user_id = auth.uid()
    )
  );

create policy "Workspace members can manage epics"
  on public.epics for all
  using (
    workspace_id in (
      select workspace_id from public.workspace_members where user_id = auth.uid()
    )
  );

-- Tasks
create table public.tasks (
  id uuid primary key default gen_random_uuid(),
  epic_id uuid not null references public.epics(id) on delete cascade,
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  title text not null,
  description text,
  estimated_days integer,
  priority text not null default 'p1' check (priority in ('p0', 'p1', 'p2')),
  status text not null default 'open' check (status in ('open', 'in_review', 'done')),
  assignee text,
  sort_order integer not null default 0,
  dependencies uuid[] not null default '{}',
  embedding extensions.vector(768),
  version integer not null default 1,
  created_at timestamptz not null default now()
);

alter table public.tasks enable row level security;

create policy "Workspace members can read tasks"
  on public.tasks for select
  using (
    workspace_id in (
      select workspace_id from public.workspace_members where user_id = auth.uid()
    )
  );

create policy "Workspace members can manage tasks"
  on public.tasks for all
  using (
    workspace_id in (
      select workspace_id from public.workspace_members where user_id = auth.uid()
    )
  );

create index idx_tasks_workspace on public.tasks(workspace_id);
create index idx_tasks_epic on public.tasks(epic_id);

-- GitHub issues
create table public.github_issues (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  github_id bigint not null,
  number integer not null,
  title text not null,
  state text not null,
  linked_task_id uuid references public.tasks(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (workspace_id, github_id)
);

alter table public.github_issues enable row level security;

create policy "Workspace members can read github issues"
  on public.github_issues for select
  using (
    workspace_id in (
      select workspace_id from public.workspace_members where user_id = auth.uid()
    )
  );

-- GitHub PRs
create table public.github_prs (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  github_id bigint not null,
  number integer not null,
  title text not null,
  state text not null,
  merged boolean not null default false,
  linked_task_id uuid references public.tasks(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (workspace_id, github_id)
);

alter table public.github_prs enable row level security;

create policy "Workspace members can read github prs"
  on public.github_prs for select
  using (
    workspace_id in (
      select workspace_id from public.workspace_members where user_id = auth.uid()
    )
  );

-- Match proposals
create table public.match_proposals (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  task_id uuid not null references public.tasks(id) on delete cascade,
  github_issue_id uuid references public.github_issues(id) on delete cascade,
  github_pr_id uuid references public.github_prs(id) on delete cascade,
  status text not null default 'pending' check (status in ('pending', 'accepted', 'rejected')),
  similarity_score real,
  created_at timestamptz not null default now()
);

alter table public.match_proposals enable row level security;

create policy "Workspace members can read match proposals"
  on public.match_proposals for select
  using (
    workspace_id in (
      select workspace_id from public.workspace_members where user_id = auth.uid()
    )
  );

create policy "Workspace members can manage match proposals"
  on public.match_proposals for all
  using (
    workspace_id in (
      select workspace_id from public.workspace_members where user_id = auth.uid()
    )
  );

-- Ingestions (cached decompositions)
create table public.ingestions (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  content_hash text not null,
  raw_content text not null,
  decomposition jsonb,
  created_at timestamptz not null default now()
);

alter table public.ingestions enable row level security;

create policy "Workspace members can read ingestions"
  on public.ingestions for select
  using (
    workspace_id in (
      select workspace_id from public.workspace_members where user_id = auth.uid()
    )
  );

-- AI usage tracking
create table public.ai_usage (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  model text not null,
  tokens_in integer not null default 0,
  tokens_out integer not null default 0,
  created_at timestamptz not null default now()
);

alter table public.ai_usage enable row level security;

create policy "Users can read own ai usage"
  on public.ai_usage for select
  using (auth.uid() = user_id);

create index idx_ai_usage_user on public.ai_usage(user_id);
create index idx_ai_usage_workspace on public.ai_usage(workspace_id);

-- Enable realtime for live dashboard updates
alter publication supabase_realtime add table public.tasks;
alter publication supabase_realtime add table public.github_issues;
alter publication supabase_realtime add table public.github_prs;
alter publication supabase_realtime add table public.match_proposals;
