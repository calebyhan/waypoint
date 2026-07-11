-- Permission tier for a workspace membership: owner / pm / member.
-- Distinct from team_members.role, which is a job-function label (frontend/backend/etc.)
-- used for scheduling/capacity and has nothing to do with permissions.
alter table public.workspace_members
  add column role text not null default 'member'
  check (role in ('owner', 'pm', 'member'));

-- Backfill: whoever is workspaces.owner_id becomes role='owner' in their membership row.
update public.workspace_members wm
set role = 'owner'
from public.workspaces w
where w.id = wm.workspace_id and w.owner_id = wm.user_id;

-- Pending invitations, keyed by GitHub username since auth is GitHub-OAuth-only.
-- Resolved automatically the next time that GitHub user logs in (see auth callback).
create table public.workspace_invites (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  github_username text not null,
  role text not null default 'member' check (role in ('pm', 'member')),
  invited_by uuid not null references public.profiles(id),
  status text not null default 'pending' check (status in ('pending', 'accepted', 'revoked')),
  created_at timestamptz not null default now()
);

create unique index uq_workspace_invites_pending
  on public.workspace_invites (workspace_id, github_username)
  where status = 'pending';

alter table public.workspace_invites enable row level security;

create policy "Workspace pm/owner can read invites"
  on public.workspace_invites for select
  using (
    workspace_id in (
      select workspace_id from public.workspace_members
      where user_id = auth.uid() and role in ('owner', 'pm')
    )
  );

create policy "Workspace pm/owner can manage invites"
  on public.workspace_invites for all
  using (
    workspace_id in (
      select workspace_id from public.workspace_members
      where user_id = auth.uid() and role in ('owner', 'pm')
    )
  );

-- Bridge from the scheduling roster to a real platform account, populated
-- manually once the named person has actually joined the workspace.
alter table public.team_members
  add column user_id uuid references public.profiles(id) on delete set null;

-- Replace blanket/owner-only "manage members" policies with role-aware ones.
-- Note the wm2 alias below: this policy is on workspace_members itself, so the
-- role lookup has to be a self-join against the same table under a different name.
drop policy "Workspace owners can manage members" on public.workspace_members;
create policy "Workspace pm/owner can manage members"
  on public.workspace_members for all
  using (
    workspace_id in (
      select workspace_id from public.workspace_members wm2
      where wm2.user_id = auth.uid() and wm2.role in ('owner', 'pm')
    )
  );

drop policy "Workspace members can manage team members" on public.team_members;
create policy "Workspace pm/owner can manage team members"
  on public.team_members for all
  using (
    workspace_id in (
      select workspace_id from public.workspace_members
      where user_id = auth.uid() and role in ('owner', 'pm')
    )
  );
