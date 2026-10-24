-- Run once in Supabase: SQL Editor -> New query -> paste -> Run.
-- One table holds every synced record (ideas and sections) as JSON.

create table if not exists public.records (
  user_id    uuid not null default auth.uid() references auth.users (id) on delete cascade,
  kind       text not null check (kind in ('ideas', 'sections')),
  id         text not null,
  data       jsonb not null,
  updated_at timestamptz not null,
  -- Set by the server on every write; devices pull everything newer than their last pull.
  synced_at  timestamptz not null default now(),
  primary key (user_id, kind, id)
);

create index if not exists records_user_synced on public.records (user_id, synced_at);

create or replace function public.touch_synced_at() returns trigger
language plpgsql as $$
begin
  new.synced_at := clock_timestamp();
  return new;
end $$;

drop trigger if exists records_touch on public.records;
create trigger records_touch before insert or update on public.records
  for each row execute function public.touch_synced_at();

-- Each user can only see and change their own records.
alter table public.records enable row level security;

drop policy if exists "own records" on public.records;
create policy "own records" on public.records
  for all to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());
