-- Invite delivery + a general notification feed.
--
-- Context: auth is GitHub-OAuth-only and invites are keyed by GitHub username,
-- so for someone who has not signed up yet we hold no email address and have no
-- way to reach them. Membership already resolves itself on their first login
-- (see auth._resolve_pending_invites) — the missing piece was purely *discovery*:
-- nothing ever told them an invite existed. A tokenized invite URL closes that
-- gap without requiring any contact channel: the PM delivers it over whatever
-- medium they already use to talk to the person.

-- Unguessable per-invite token backing /invite/<token>. Nullable so the column
-- can be added to existing rows, then backfilled and made NOT NULL below.
alter table public.workspace_invites add column token text;

-- Backfill pre-existing invites. gen_random_bytes lives in pgcrypto, which
-- Supabase enables by default; encode(...,'base64') is then made URL-safe.
update public.workspace_invites
set token = replace(replace(encode(gen_random_bytes(32), 'base64'), '/', '_'), '+', '-')
where token is null;

alter table public.workspace_invites alter column token set not null;
create unique index uq_workspace_invites_token on public.workspace_invites (token);

-- Records who actually consumed the invite. Distinct from invited_by, and from
-- the github_username the invite was addressed to: an invite is bound to that
-- username, so this is an audit trail of the binding actually being satisfied.
alter table public.workspace_invites
  add column accepted_by uuid references public.profiles(id) on delete set null;

-- The public GET /invites/{token} preview endpoint reads an invite with no
-- authenticated user, so it runs through the service-role key rather than RLS.
-- No anon policy is added here on purpose: possession of the token is the
-- authorization, and it is checked in the router.


-- In-app notification feed.
--
-- user_id is nullable and github_username is its stand-in precisely because of
-- the pre-account case: a notification can be addressed to a GitHub username
-- before any profile row exists for that person, and is claimed (user_id filled
-- in) the first time they sign in. Exactly one of the two must be set.
create table public.notifications (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references public.profiles(id) on delete cascade,
  github_username text,
  workspace_id uuid references public.workspaces(id) on delete cascade,
  type text not null,
  payload jsonb not null default '{}'::jsonb,
  read_at timestamptz,
  created_at timestamptz not null default now(),
  constraint notifications_addressee_check check (
    (user_id is not null) or (github_username is not null)
  )
);

-- Feed query: newest-first for one user.
create index idx_notifications_user_created
  on public.notifications (user_id, created_at desc);

-- Unread-badge count, and the login-time claim scan.
create index idx_notifications_unread
  on public.notifications (user_id)
  where read_at is null;

create index idx_notifications_unclaimed
  on public.notifications (github_username)
  where user_id is null;

alter table public.notifications enable row level security;

-- A user may only ever see their own notifications. Unclaimed rows
-- (user_id is null) match no one until the claim step fills them in.
create policy "Users can read their own notifications"
  on public.notifications for select
  using (user_id = auth.uid());

create policy "Users can update their own notifications"
  on public.notifications for update
  using (user_id = auth.uid());
