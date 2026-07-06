-- Execute no SQL Editor do seu projeto Supabase
-- (https://supabase.com/dashboard → SQL Editor)

-- 1. Tabela de sessões
CREATE TABLE IF NOT EXISTS sessions (
  id               TEXT        PRIMARY KEY,
  competencia      TEXT        NOT NULL,
  resultado        JSONB       NOT NULL,
  storage_path     TEXT,
  output_filename  TEXT,
  created_at       TIMESTAMPTZ DEFAULT NOW()
);

-- Índice para limpeza automática de sessões antigas (opcional)
CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON sessions (created_at);

-- 2. Limpeza automática de sessões com mais de 7 dias (opcional)
-- Requer pg_cron habilitado no Supabase (disponível em planos pagos)
-- SELECT cron.schedule('cleanup-sessions', '0 3 * * *',
--   $$DELETE FROM sessions WHERE created_at < NOW() - INTERVAL '7 days'$$);

-- 3. Row Level Security — desabilitar para uso interno
ALTER TABLE sessions DISABLE ROW LEVEL SECURITY;
