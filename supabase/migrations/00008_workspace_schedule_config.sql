alter table public.workspaces
  add column schedule_start_date date,
  add column tickets_per_member_per_week numeric not null default 0,
  add column assign_day integer not null default -1;
