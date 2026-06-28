alter table public.tasks
  add column motivation text,
  add column deliverables text[] not null default '{}',
  add column important_notes text[] not null default '{}';
