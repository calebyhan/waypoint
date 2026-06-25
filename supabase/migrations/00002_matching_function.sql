-- Cosine similarity search for semantic issue/PR matching
create or replace function match_tasks_by_embedding(
  query_embedding extensions.vector(768),
  match_workspace_id uuid,
  match_threshold float,
  match_count int
)
returns table (
  id uuid,
  title text,
  similarity float
)
language sql stable
set search_path = public, extensions
as $$
  select
    tasks.id,
    tasks.title,
    1 - (tasks.embedding <=> query_embedding) as similarity
  from public.tasks
  where tasks.workspace_id = match_workspace_id
    and tasks.embedding is not null
    and 1 - (tasks.embedding <=> query_embedding) > match_threshold
  order by tasks.embedding <=> query_embedding
  limit match_count;
$$;
