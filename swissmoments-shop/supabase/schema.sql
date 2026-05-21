-- SwissMoments — Datenbank-Schema
-- Diese Datei einmal in Supabase → SQL Editor ausführen.
-- Danach im Storage-Tab einen privaten Bucket `ebooks` anlegen.

create extension if not exists "pgcrypto";

create table if not exists orders (
  id uuid primary key default gen_random_uuid(),
  stripe_session_id text unique not null,
  customer_email text not null,
  customer_name text,
  amount_total integer not null,   -- in Rappen
  currency text not null default 'chf',
  status text not null default 'paid',
  created_at timestamptz not null default now()
);

create index if not exists orders_created_at_idx on orders (created_at desc);
create index if not exists orders_email_idx on orders (customer_email);

create table if not exists order_items (
  id uuid primary key default gen_random_uuid(),
  order_id uuid not null references orders(id) on delete cascade,
  product_slug text not null,
  product_title text not null,
  unit_price integer not null,     -- in Rappen
  quantity integer not null default 1
);

create index if not exists order_items_order_idx on order_items (order_id);

-- products_files: verknüpft einen Produkt-Slug mit einer Datei im Storage.
-- Wird vom Admin-Upload befüllt.
create table if not exists products_files (
  slug text primary key,
  storage_path text not null,      -- z.B. ebooks/die-vergessene-schweiz.pdf
  filename text not null,
  size_bytes bigint,
  updated_at timestamptz not null default now()
);

-- Row-Level-Security: alles dicht. Wir greifen nur per Service-Role-Key zu.
alter table orders enable row level security;
alter table order_items enable row level security;
alter table products_files enable row level security;
