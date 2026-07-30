-- Execute no SQL Editor do Supabase (https://supabase.com/dashboard → SQL Editor)
-- Tabela de sessões do módulo IRPJ/CSLL — independente da tabela "sessions" do PIS/COFINS,
-- para permitir filtro de competência próprio deste módulo.

CREATE TABLE IF NOT EXISTS sessions_irpj_csll (
  id               TEXT        PRIMARY KEY,
  competencia      TEXT        NOT NULL,
  resultado        JSONB       NOT NULL,
  storage_path     TEXT,
  output_filename  TEXT,
  created_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sessions_irpj_csll_created_at ON sessions_irpj_csll (created_at);
CREATE INDEX IF NOT EXISTS idx_sessions_irpj_csll_competencia ON sessions_irpj_csll (competencia);

-- Uso interno (mesmo padrão de "sessions") — acesso apenas pela chave usada no backend.
ALTER TABLE sessions_irpj_csll DISABLE ROW LEVEL SECURITY;
