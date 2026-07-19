-- AI pipeline reliability: idempotency + cache-row uniqueness.
--
-- 1) reingest_applications: client-supplied idempotency keys so a
--    double-submitted POST /reingest/approve applies its changes exactly once.
-- 2) ingestions unique(workspace_id, content_hash): collapses concurrent
--    duplicate ingests of identical content onto a single cache row, letting
--    the app upsert (on_conflict) instead of insert.

create table public.reingest_applications (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  idempotency_key text not null,
  created_at timestamptz not null default now(),
  unique (workspace_id, idempotency_key)
);

alter table public.reingest_applications enable row level security;

create policy "Workspace members can manage reingest applications"
  on public.reingest_applications for all
  using (
    workspace_id in (
      select workspace_id from public.workspace_members where user_id = auth.uid()
    )
  );

-- Dedupe any existing duplicate cache rows (keep the newest) before adding
-- the unique constraint.
delete from public.ingestions a
using public.ingestions b
where a.workspace_id = b.workspace_id
  and a.content_hash = b.content_hash
  and (a.created_at < b.created_at
       or (a.created_at = b.created_at and a.id < b.id));

alter table public.ingestions
  add constraint ingestions_workspace_hash_unique unique (workspace_id, content_hash);
