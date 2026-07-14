-- Prevent two active workspaces from claiming the same GitHub repo
-- (repo-squatting would let one workspace's webhook secret silently break
-- another workspace's inbound webhook deliveries).
create unique index uq_workspaces_active_repo
  on public.workspaces (repo_owner, repo_name)
  where repo_owner is not null and state = 'active';
