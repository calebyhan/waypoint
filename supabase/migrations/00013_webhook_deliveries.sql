-- Replay protection for GitHub webhooks: record each X-GitHub-Delivery UUID
-- so a captured payload cannot be re-submitted and re-processed.
-- Rows only need short retention (GitHub redeliveries happen within days);
-- old rows can be purged with:
--   delete from public.github_webhook_deliveries where received_at < now() - interval '7 days';
create table public.github_webhook_deliveries (
  id uuid primary key default gen_random_uuid(),
  delivery_id text not null unique,
  received_at timestamptz not null default now()
);

create index idx_github_webhook_deliveries_received_at
  on public.github_webhook_deliveries (received_at);
