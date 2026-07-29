-- Core schema: global catalog (public-read) + household-scoped data (RLS).
-- Multi-tenancy: users belong to households via household_members; every
-- household-scoped table's policies route through is_household_member().

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- Global / public-read: controlled vocabulary + shared catalog
-- ---------------------------------------------------------------------------

create table allergen_classes (
  id text primary key,          -- 'dairy', 'gluten', 'peanut', ...
  display_name text not null
);

create table canonical_items (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  aliases text[] not null default '{}',
  store_section text not null check (store_section in
    ('produce','meat_seafood','dairy','pantry','frozen','bakery','other')),
  perishability text not null check (perishability in
    ('tender_herb','hardy_herb','perishable','stable')),
  typical_price_cents int,
  created_at timestamptz not null default now()
);

-- Membership decided ONLY here — no name/substring matching anywhere.
-- is_member=false rows are explicit negative assertions (coconut milk ≠ dairy)
-- kept as documentation and regression data.
create table item_allergens (
  canonical_item_id uuid not null references canonical_items(id) on delete cascade,
  allergen_class_id text not null references allergen_classes(id),
  is_member boolean not null,
  primary key (canonical_item_id, allergen_class_id)
);

create table unit_conversions (
  id uuid primary key default gen_random_uuid(),
  canonical_item_id uuid references canonical_items(id) on delete cascade,
  from_qty numeric not null,
  from_unit text not null,
  to_qty numeric not null,
  to_unit text not null,
  note text
);

-- Recipes: global seed rows have household_id NULL and is_public=true;
-- user-imported rows are household-scoped and NEVER public (licensing).
create table recipes (
  id uuid primary key default gen_random_uuid(),
  household_id uuid,            -- FK added after households is created
  is_public boolean not null default false,
  title text not null,
  serves int not null check (serves > 0),
  published_time_min int check (published_time_min > 0),
  protein text not null,
  cuisine text not null,
  seasons text[] not null default '{year_round}',
  equipment text[] not null default '{}',
  effort text not null default 'moderate' check (effort in ('easy','moderate','involved')),
  license text,                 -- required for public rows (enforced below)
  source_attribution text,
  source_url text,
  created_at timestamptz not null default now(),
  constraint public_needs_license check (not is_public or license is not null),
  constraint public_xor_household check (is_public = (household_id is null))
);

create table recipe_ingredients (
  id uuid primary key default gen_random_uuid(),
  recipe_id uuid not null references recipes(id) on delete cascade,
  position int not null,
  raw text not null,
  qty numeric check (qty > 0),
  unit text,
  canonical_item_id uuid references canonical_items(id),
  prep_note text,
  is_optional boolean not null default false,
  added_at_step int check (added_at_step > 0)   -- enables Split handling
);

create table recipe_steps (
  id uuid primary key default gen_random_uuid(),
  recipe_id uuid not null references recipes(id) on delete cascade,
  step_order int not null,
  text text not null,
  duration_min int check (duration_min >= 0),
  unattended boolean not null default false     -- drives long-lead detection
);

-- ---------------------------------------------------------------------------
-- Household-scoped
-- ---------------------------------------------------------------------------

create table households (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  region text not null default 'northern' check (region in ('northern','southern')),
  dinners_per_week int not null default 5 check (dinners_per_week between 1 and 7),
  budget_cents_weekly int check (budget_cents_weekly > 0),
  budget_enabled boolean not null default false,
  plan_tier text not null default 'byo_key',
  created_at timestamptz not null default now()
);

alter table recipes
  add constraint recipes_household_fk
  foreign key (household_id) references households(id) on delete cascade;

create table household_members (
  household_id uuid not null references households(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null default 'adult' check (role in ('owner','adult','viewer')),
  primary key (household_id, user_id)
);

create table people (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references households(id) on delete cascade,
  name text not null,
  is_child boolean not null default false,
  eats_planned_dinners boolean not null default true
);

create table dietary_restrictions (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references households(id) on delete cascade,
  person_id uuid not null references people(id) on delete cascade,
  allergen_class_id text references allergen_classes(id),
  canonical_item_id uuid references canonical_items(id),
  severity text not null check (severity in ('allergy','intolerance','preference')),
  default_handling text check (default_handling in ('clear','substitute','split','skip')),
  substitute_item_id uuid references canonical_items(id),
  notes text,
  constraint restriction_target check
    ((allergen_class_id is null) <> (canonical_item_id is null))
);

create table recipe_household_state (
  household_id uuid not null references households(id) on delete cascade,
  recipe_id uuid not null references recipes(id) on delete cascade,
  lifecycle text not null default 'to_try' check (lifecycle in ('to_try','probation','keeper','cut')),
  last_made_at date,
  times_made int not null default 0,
  avg_rating numeric check (avg_rating between 1 and 5),
  real_time_min int check (real_time_min > 0),  -- measured; never overwrites published_time_min
  primary key (household_id, recipe_id)
);

create table meal_plans (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references households(id) on delete cascade,
  week_start date not null,
  status text not null default 'draft' check (status in ('draft','confirmed','archived')),
  prompt_version text,           -- provenance when AI-generated
  model text,
  created_at timestamptz not null default now(),
  unique (household_id, week_start)
);

create table meal_plan_entries (
  id uuid primary key default gen_random_uuid(),
  meal_plan_id uuid not null references meal_plans(id) on delete cascade,
  household_id uuid not null references households(id) on delete cascade,
  recipe_id uuid not null references recipes(id),
  plan_date date not null,
  servings int not null check (servings > 0),
  status text not null default 'pending' check (status in ('pending','cooked','skipped','moved')),
  rationale text
);

create table entry_person_handling (
  meal_plan_entry_id uuid not null references meal_plan_entries(id) on delete cascade,
  person_id uuid not null references people(id) on delete cascade,
  household_id uuid not null references households(id) on delete cascade,
  handling text not null check (handling in ('clear','substitute','split','skip')),
  substitute_item_id uuid references canonical_items(id),
  substitute_note text,
  primary key (meal_plan_entry_id, person_id)
);

create table long_lead_flags (
  id uuid primary key default gen_random_uuid(),
  meal_plan_entry_id uuid not null references meal_plan_entries(id) on delete cascade,
  household_id uuid not null references households(id) on delete cascade,
  kind text not null,            -- marinade / thaw / brine / slow_cook / other
  lead_min int not null check (lead_min > 0),
  notify_at timestamptz
);

create table pantry_items (
  household_id uuid not null references households(id) on delete cascade,
  canonical_item_id uuid not null references canonical_items(id),
  qty numeric not null check (qty >= 0),
  unit text not null,
  confidence text not null default 'assumed' check (confidence in ('confirmed','assumed')),
  updated_at timestamptz not null default now(),
  primary key (household_id, canonical_item_id)
);

create table grocery_lists (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references households(id) on delete cascade,
  meal_plan_id uuid references meal_plans(id) on delete set null,
  status text not null default 'open' check (status in ('open','ordered','done')),
  created_at timestamptz not null default now()
);

create table grocery_list_items (
  id uuid primary key default gen_random_uuid(),
  grocery_list_id uuid not null references grocery_lists(id) on delete cascade,
  household_id uuid not null references households(id) on delete cascade,
  canonical_item_id uuid references canonical_items(id),
  display_name text not null,
  qty numeric,
  unit text,
  section text not null default 'other',
  origin text not null default 'recipe' check (origin in ('recipe','standing','restock','treat')),
  est_price_cents int,
  checked boolean not null default false
);

create table standing_orders (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references households(id) on delete cascade,
  canonical_item_id uuid references canonical_items(id),
  raw text not null,
  qty numeric,
  unit text,
  reason text                    -- kids' standing meals / breakfast / restock
);

create table ratings (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references households(id) on delete cascade,
  meal_plan_entry_id uuid not null references meal_plan_entries(id) on delete cascade,
  person_id uuid references people(id) on delete set null,
  score int check (score between 1 and 5),
  notes text,
  cook_time_actual_min int check (cook_time_actual_min > 0),
  created_at timestamptz not null default now()
);

create table learnings (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references households(id) on delete cascade,
  scope text not null check (scope in ('recipe','standing','unit_conversion','sourcing_gap')),
  recipe_id uuid references recipes(id) on delete set null,
  text text not null,
  structured_payload jsonb,
  created_at timestamptz not null default now()
);

create table cook_sessions (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references households(id) on delete cascade,
  meal_plan_entry_id uuid not null references meal_plan_entries(id) on delete cascade,
  started_at timestamptz not null default now(),
  completed_at timestamptz,
  step_timestamps jsonb not null default '[]'   -- passive real_time capture
);

create table retailer_connections (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references households(id) on delete cascade,
  retailer text not null,
  status text not null default 'pending' check (status in ('pending','connected','revoked')),
  store_location_id text,
  -- OAuth tokens live server-side only (Edge Function storage), referenced by id.
  token_ref uuid,
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- RLS
-- ---------------------------------------------------------------------------

create or replace function is_household_member(hid uuid)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from household_members
    where household_id = hid and user_id = auth.uid()
  );
$$;

-- Global tables: public read, service-role-only write.
alter table allergen_classes enable row level security;
alter table canonical_items enable row level security;
alter table item_allergens enable row level security;
alter table unit_conversions enable row level security;
create policy "public read" on allergen_classes for select using (true);
create policy "public read" on canonical_items for select using (true);
create policy "public read" on item_allergens for select using (true);
create policy "public read" on unit_conversions for select using (true);

-- Recipes: public rows readable by all; household rows member-only.
alter table recipes enable row level security;
create policy "read public or own" on recipes for select
  using (is_public or (household_id is not null and is_household_member(household_id)));
create policy "insert own" on recipes for insert
  with check (household_id is not null and is_household_member(household_id) and not is_public);
create policy "update own" on recipes for update
  using (household_id is not null and is_household_member(household_id));
create policy "delete own" on recipes for delete
  using (household_id is not null and is_household_member(household_id));

alter table recipe_ingredients enable row level security;
alter table recipe_steps enable row level security;
create policy "read via recipe" on recipe_ingredients for select
  using (exists (select 1 from recipes r where r.id = recipe_id
         and (r.is_public or (r.household_id is not null and is_household_member(r.household_id)))));
create policy "write via recipe" on recipe_ingredients for all
  using (exists (select 1 from recipes r where r.id = recipe_id
         and r.household_id is not null and is_household_member(r.household_id)))
  with check (exists (select 1 from recipes r where r.id = recipe_id
         and r.household_id is not null and is_household_member(r.household_id)));
create policy "read via recipe" on recipe_steps for select
  using (exists (select 1 from recipes r where r.id = recipe_id
         and (r.is_public or (r.household_id is not null and is_household_member(r.household_id)))));
create policy "write via recipe" on recipe_steps for all
  using (exists (select 1 from recipes r where r.id = recipe_id
         and r.household_id is not null and is_household_member(r.household_id)))
  with check (exists (select 1 from recipes r where r.id = recipe_id
         and r.household_id is not null and is_household_member(r.household_id)));

-- households: members read/update; anyone authenticated can create.
alter table households enable row level security;
create policy "member read" on households for select using (is_household_member(id));
create policy "member update" on households for update using (is_household_member(id));
create policy "authenticated insert" on households for insert
  with check (auth.uid() is not null);

-- household_members: members see their household's roster; owners manage it.
alter table household_members enable row level security;
create policy "member read" on household_members for select
  using (is_household_member(household_id));
create policy "self insert" on household_members for insert
  with check (user_id = auth.uid());
create policy "owner delete" on household_members for delete
  using (exists (select 1 from household_members m
         where m.household_id = household_members.household_id
           and m.user_id = auth.uid() and m.role = 'owner'));

-- All remaining household-scoped tables share one policy shape.
do $$
declare t text;
begin
  foreach t in array array[
    'people','dietary_restrictions','recipe_household_state','meal_plans',
    'meal_plan_entries','entry_person_handling','long_lead_flags','pantry_items',
    'grocery_lists','grocery_list_items','standing_orders','ratings','learnings',
    'cook_sessions','retailer_connections'
  ] loop
    execute format('alter table %I enable row level security', t);
    execute format(
      'create policy "member all" on %I for all using (is_household_member(household_id)) with check (is_household_member(household_id))', t);
  end loop;
end $$;

-- Helpful indexes for the hot paths.
create index on recipes (is_public) where is_public;
create index on recipes (household_id) where household_id is not null;
create index on recipe_ingredients (recipe_id);
create index on recipe_steps (recipe_id);
create index on meal_plan_entries (household_id, plan_date);
create index on grocery_list_items (grocery_list_id);
create index on pantry_items (household_id);
