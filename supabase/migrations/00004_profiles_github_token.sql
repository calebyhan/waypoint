-- Supabase Auth does not persist OAuth provider access tokens after sign-in;
-- they're only present on the session returned at login time. Add a column
-- so the backend can capture and reuse the GitHub token for API calls.
alter table public.profiles add column github_token text;
