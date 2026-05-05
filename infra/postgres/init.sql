-- Расширения, нужные для будущих этапов и для производительности.
CREATE EXTENSION IF NOT EXISTS pgcrypto;     -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS citext;       -- регистронезависимые строки (промокоды и т.п.)
CREATE EXTENSION IF NOT EXISTS pg_trgm;      -- быстрый поиск по подстроке (юзеры в админке)
