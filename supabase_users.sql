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

-- 5. Função RPC para criar usuário (hash bcrypt via pgcrypto — sem expor senha ao backend)
--    Retorna 'ok' se criado, 'duplicate' se username já existe.
CREATE OR REPLACE FUNCTION create_user_rpc(
  p_username  TEXT,
  p_password  TEXT,
  p_full_name TEXT DEFAULT NULL
)
RETURNS TEXT LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM users WHERE username = p_username) THEN
    RETURN 'duplicate';
  END IF;
  INSERT INTO users (username, password_hash, full_name, active)
  VALUES (p_username, crypt(p_password, gen_salt('bf', 12)), p_full_name, TRUE);
  RETURN 'ok';
END;
$$;

-- 6. Função RPC para alterar senha (hash bcrypt via pgcrypto)
CREATE OR REPLACE FUNCTION change_password_rpc(
  p_username    TEXT,
  p_new_password TEXT
)
RETURNS void LANGUAGE sql SECURITY DEFINER AS $$
  UPDATE users
  SET password_hash = crypt(p_new_password, gen_salt('bf', 12))
  WHERE username = p_username;
$$;

-- 7. Função RPC para listar usuários (SECURITY DEFINER contorna restrição da chave anon)
CREATE OR REPLACE FUNCTION listar_usuarios_rpc()
RETURNS TABLE(
  id UUID, username TEXT, full_name TEXT,
  active BOOLEAN, created_at TIMESTAMPTZ, last_login TIMESTAMPTZ
)
LANGUAGE sql SECURITY DEFINER AS $$
  SELECT id, username, full_name, active, created_at, last_login
  FROM users ORDER BY created_at ASC;
$$;

-- 8. Função RPC para ativar/desativar usuário
CREATE OR REPLACE FUNCTION toggle_usuario_rpc(p_username TEXT, p_active BOOLEAN)
RETURNS void LANGUAGE sql SECURITY DEFINER AS $$
  UPDATE users SET active = p_active WHERE username = p_username;
$$;

-- 9. Função RPC para excluir usuário
CREATE OR REPLACE FUNCTION excluir_usuario_rpc(p_username TEXT)
RETURNS void LANGUAGE sql SECURITY DEFINER AS $$
  DELETE FROM users WHERE username = p_username;
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
