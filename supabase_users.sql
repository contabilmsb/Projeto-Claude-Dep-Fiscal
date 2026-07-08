-- ══════════════════════════════════════════════════════════════════
--  Portal PIS/COFINS — Gestão de Usuários
--  Execute no SQL Editor do Supabase
-- ══════════════════════════════════════════════════════════════════

-- 1. Habilita extensão de criptografia (bcrypt)
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 2. Tabela de usuários
CREATE TABLE IF NOT EXISTS users (
  id           UUID        DEFAULT gen_random_uuid() PRIMARY KEY,
  username     TEXT        NOT NULL UNIQUE,
  password_hash TEXT       NOT NULL,   -- bcrypt via pgcrypto
  full_name    TEXT,
  active       BOOLEAN     DEFAULT TRUE,
  created_at   TIMESTAMPTZ DEFAULT NOW(),
  last_login   TIMESTAMPTZ
);

-- Desabilita RLS (acesso apenas pelo service role / backend)
ALTER TABLE users DISABLE ROW LEVEL SECURITY;

-- 3. Função RPC para validar login (backend chama via supabase.rpc)
--    Retorna o usuário se credenciais válidas, vazio se inválidas.
CREATE OR REPLACE FUNCTION verify_user(p_username TEXT, p_password TEXT)
RETURNS TABLE(id UUID, username TEXT, full_name TEXT)
LANGUAGE sql
SECURITY DEFINER
AS $$
  SELECT id, username, full_name
  FROM users
  WHERE username      = p_username
    AND password_hash = crypt(p_password, password_hash)
    AND active        = TRUE;
$$;

-- 4. Função para atualizar last_login
CREATE OR REPLACE FUNCTION touch_last_login(p_username TEXT)
RETURNS void LANGUAGE sql SECURITY DEFINER AS $$
  UPDATE users SET last_login = NOW() WHERE username = p_username;
$$;

-- ══════════════════════════════════════════════════════════════════
--  INSERIR / GERENCIAR USUÁRIOS
--  Troque 'usuario' e 'senha' pelos valores reais.
--  O pgcrypto gera o hash bcrypt automaticamente — nunca armazena
--  a senha em texto puro.
-- ══════════════════════════════════════════════════════════════════

-- Inserir usuário:
-- INSERT INTO users (username, password_hash, full_name)
-- VALUES ('daiana', crypt('SuaSenha123!', gen_salt('bf', 12)), 'Daiana Leite');

-- Alterar senha:
-- UPDATE users SET password_hash = crypt('NovaSenha456!', gen_salt('bf', 12))
-- WHERE username = 'daiana';

-- Desativar usuário (sem excluir):
-- UPDATE users SET active = FALSE WHERE username = 'daiana';

-- Reativar usuário:
-- UPDATE users SET active = TRUE WHERE username = 'daiana';

-- Listar todos os usuários:
-- SELECT id, username, full_name, active, created_at, last_login FROM users ORDER BY created_at;

-- Excluir usuário:
-- DELETE FROM users WHERE username = 'daiana';

-- ══════════════════════════════════════════════════════════════════
--  EXEMPLO — insere usuário admin inicial
--  TROQUE a senha antes de executar!
-- ══════════════════════════════════════════════════════════════════
-- INSERT INTO users (username, password_hash, full_name)
-- VALUES ('admin', crypt('Trocar@2026!', gen_salt('bf', 12)), 'Administrador');
