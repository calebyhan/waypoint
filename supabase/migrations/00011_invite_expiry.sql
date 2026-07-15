-- Invites expire 14 days after creation; expired invites can no longer be
-- auto-accepted on login and must be re-issued.
alter table public.workspace_invites
  add column expires_at timestamptz not null default (now() + interval '14 days');

-- Add an explicit 'expired' terminal status so stale invites are distinguishable
-- from ones a PM deliberately revoked.
alter table public.workspace_invites
  drop constraint workspace_invites_status_check;
alter table public.workspace_invites
  add constraint workspace_invites_status_check
  check (status in ('pending', 'accepted', 'revoked', 'expired'));
