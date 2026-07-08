"""
Portal Web — Apuração PIS/COFINS
FastAPI backend: recebe uploads, processa e retorna resultados JSON + Excel.

Armazenamento:
  - Local (desenvolvimento): OUTPUT_DIR em disco + _sessions em memória
  - Supabase (produção):     Storage bucket + tabela sessions
"""

import sys
import os
import uuid
import json
import hmac
import time
import base64
import hashlib
import shutil
import tempfile
import bcrypt
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.readers import load_all
from src.calculator import calcular
from src.validator import validar
from src.writer import atualizar_template

app = FastAPI(title="Apuração PIS/COFINS")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "static"

# Serve arquivos estáticos (logo, etc.) — funciona local e no Vercel
try:
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
except Exception:
    pass
OUTPUT_DIR = Path(__file__).parent.parent / "output"
# Cria apenas localmente; no Vercel o filesystem é read-only
try:
    OUTPUT_DIR.mkdir(exist_ok=True)
except OSError:
    OUTPUT_DIR = Path(tempfile.gettempdir())

COFINS_RATE = 0.03
PIS_RATE    = 0.0065

# ── Autenticação ──────────────────────────────────────────────────────────────
APP_USERNAME = os.getenv("APP_USERNAME", "admin")
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
APP_SECRET   = os.getenv("APP_SECRET", "dev-secret-change-in-production")
TOKEN_TTL    = 12 * 3600  # 12 horas


def _make_token(username: str) -> str:
    payload = base64.b64encode(
        json.dumps({"u": username, "t": int(time.time())}).encode()
    ).decode()
    sig = hmac.new(APP_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def _verify_token(token: str) -> bool:
    try:
        payload, sig = token.rsplit(".", 1)
        expected = hmac.new(APP_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return False
        data = json.loads(base64.b64decode(payload))
        return time.time() - data["t"] < TOKEN_TTL
    except Exception:
        return False


def require_auth(request: Request):
    token = request.headers.get("X-Auth-Token", "")
    if not _verify_token(token):
        raise HTTPException(status_code=401, detail="Não autenticado. Faça login.")

# ── Supabase (opcional — ativo quando SUPABASE_URL estiver definido) ──────────
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
SUPABASE_BUCKET = "apuracao-output"

_supabase_client = None

def _get_supabase():
    global _supabase_client
    if _supabase_client is None and SUPABASE_URL and SUPABASE_KEY:
        from supabase import create_client
        _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase_client

def _use_supabase() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY)

# ── Fallback em memória (desenvolvimento local) ────────────────────────────────
_sessions: dict[str, dict] = {}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _competencia_to_month_year(competencia: str) -> tuple[int, int]:
    parts = competencia.strip().split("/")
    return int(parts[0]), int(parts[1])


def _totais_fingerprint(resultado: dict) -> dict:
    """Extrai os campos numéricos chave para comparação de duplicidade."""
    t = resultado.get("totais", {})
    c = resultado.get("cofins", {})
    p = resultado.get("pis", {})
    return {
        "total_recebido":   round(float(t.get("total_recebido",  0)), 2),
        "base_liquida":     round(float(t.get("base_liquida",    0)), 2),
        "cofins_retido":    round(float(t.get("cofins_retido",   0)), 2),
        "cofins_apurado":   round(float(c.get("valor_apurado",   0)), 2),
        "cofins_a_pagar":   round(float(c.get("valor_a_pagar",   0)), 2),
        "pis_retido":       round(float(t.get("pis_retido",      0)), 2),
        "pis_apurado":      round(float(p.get("valor_apurado",   0)), 2),
        "pis_a_pagar":      round(float(p.get("valor_a_pagar",   0)), 2),
        "csll_retida":      round(float(t.get("csll_retida",     0)), 2),
        "irrf_retido":      round(float(t.get("irrf_retido",     0)), 2),
        "juros":            round(float(t.get("juros",           0)), 2),
        "n_nfs":            len(resultado.get("consolidacao", [])),
    }


def _session_get_by_competencia(competencia: str) -> dict | None:
    """Busca sessão existente para a mesma competência."""
    if _use_supabase():
        sb = _get_supabase()
        rows = sb.table("sessions").select("*") \
            .eq("competencia", competencia) \
            .order("created_at", desc=True).limit(1).execute()
        return rows.data[0] if rows.data else None
    # Fallback local
    for sid, s in _sessions.items():
        if s["resultado"].get("competencia") == competencia:
            return {**s, "id": sid}
    return None


def _session_update(old_id: str, new_session_id: str, output_path: Path, resultado: dict):
    """Substitui sessão existente por nova (mesma competência, dados diferentes)."""
    if _use_supabase():
        sb = _get_supabase()
        # Remove arquivo antigo do Storage (ignora erros)
        try:
            old_rows = sb.table("sessions").select("storage_path").eq("id", old_id).execute()
            if old_rows.data and old_rows.data[0].get("storage_path"):
                sb.storage.from_(SUPABASE_BUCKET).remove([old_rows.data[0]["storage_path"]])
        except Exception:
            pass
        # Apaga registro antigo
        sb.table("sessions").delete().eq("id", old_id).execute()
    else:
        _sessions.pop(old_id, None)
    # Insere novo
    _session_save(new_session_id, output_path, resultado)


def _session_save(session_id: str, output_path: Path, resultado: dict):
    """Salva sessão localmente ou no Supabase."""
    if _use_supabase():
        sb = _get_supabase()
        storage_path = f"{session_id}/{output_path.name}"
        with open(output_path, "rb") as f:
            sb.storage.from_(SUPABASE_BUCKET).upload(
                storage_path,
                f.read(),
                {"content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
            )
        sb.table("sessions").insert({
            "id": session_id,
            "competencia": resultado["competencia"],
            "resultado": resultado,
            "storage_path": storage_path,
            "output_filename": output_path.name,
        }).execute()
    else:
        _sessions[session_id] = {"output_path": output_path, "resultado": resultado}


def _session_get(session_id: str) -> dict | None:
    """Recupera sessão do Supabase ou memória."""
    if _use_supabase():
        sb = _get_supabase()
        rows = sb.table("sessions").select("*").eq("id", session_id).execute()
        if rows.data:
            return rows.data[0]
        return None
    return _sessions.get(session_id)


# ── Rotas ─────────────────────────────────────────────────────────────────────

@app.post("/auth/login")
async def login(username: str = Form(...), password: str = Form(...)):
    # Valida via Supabase (tabela users com bcrypt)
    if _use_supabase():
        sb = _get_supabase()
        try:
            result = sb.rpc("verify_user", {"p_username": username, "p_password": password}).execute()
            if not result.data:
                raise HTTPException(status_code=401, detail="Usuário ou senha inválidos.")
            user = result.data[0]
            # Atualiza last_login (ignora erro se função não existir)
            try:
                sb.rpc("touch_last_login", {"p_username": username}).execute()
            except Exception:
                pass
            return {"token": _make_token(username), "username": user.get("full_name") or username}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erro ao autenticar: {e}")
    # Fallback local via env vars (desenvolvimento)
    if not APP_PASSWORD:
        raise HTTPException(status_code=503, detail="APP_PASSWORD não configurada.")
    if username == APP_USERNAME and password == APP_PASSWORD:
        return {"token": _make_token(username), "username": username}
    raise HTTPException(status_code=401, detail="Usuário ou senha inválidos.")


@app.get("/", response_class=HTMLResponse)
async def index():
    # Tenta caminhos possíveis (local e Vercel)
    candidates = [
        STATIC_DIR / "index.html",
        Path(__file__).parent / "static" / "index.html",
        Path(__file__).parent.parent / "web" / "static" / "index.html",
    ]
    for p in candidates:
        if p.exists():
            return HTMLResponse(content=p.read_text(encoding="utf-8"))
    raise HTTPException(status_code=404, detail="index.html não encontrado")


@app.post("/processar", dependencies=[Depends(require_auth)])
async def processar(
    competencia: str = Form(...),
    estornos_json: str = Form(default="[]"),
    template:   UploadFile = File(...),
    recebidas:  UploadFile = File(...),
    cofins_ret: UploadFile = File(...),
    pis_ret:    UploadFile = File(...),
    csll_ret:   UploadFile = File(...),
    irrf:       UploadFile = File(...),
    juros:      UploadFile = File(...),
    vendas:     UploadFile = File(...),
):
    session_id = str(uuid.uuid4())
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"apuracao_{session_id}_"))

    try:
        file_map = {
            "template":   template,
            "recebidas":  recebidas,
            "cofins_ret": cofins_ret,
            "pis_ret":    pis_ret,
            "csll_ret":   csll_ret,
            "irrf":       irrf,
            "juros":      juros,
            "vendas":     vendas,
        }
        paths = {}
        for key, upload in file_map.items():
            dest = tmp_dir / upload.filename
            content = await upload.read()
            dest.write_bytes(content)
            paths[key] = dest

        estornos = json.loads(estornos_json) if estornos_json else []

        dados = load_all(paths, estornos=estornos)
        resultado = calcular(dados, competencia, COFINS_RATE, PIS_RATE)
        alertas = validar(dados)

        mes, ano = _competencia_to_month_year(competencia)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        comp_fmt = competencia.replace("/", ".")

        # Em Vercel usa /tmp; localmente usa OUTPUT_DIR
        if _use_supabase():
            out_dir = Path(tempfile.gettempdir())
        else:
            out_dir = OUTPUT_DIR

        # Nome sem acentos/espaços para compatibilidade com Supabase Storage
        safe_name = f"Apuracao_PIS_COFINS_{comp_fmt}_{ts}.xlsx"
        output_path = out_dir / safe_name

        output_path, _ = atualizar_template(
            template_path=paths["template"],
            output_path=output_path,
            resultado=resultado,
            dados=dados,
            target_month=mes,
            target_year=ano,
            alertas=alertas,
        )

        consolidacao = _build_consolidacao(dados)

        resp = {
            "competencia":        competencia,
            "session_id":         session_id,
            "estornos_aplicados": estornos,
            "totais": {
                "total_recebido": round(resultado.total_recebido, 2),
                "cofins_retido":  round(resultado.cofins.retencao_fonte, 2),
                "pis_retido":     round(resultado.pis.retencao_fonte, 2),
                "csll_retida":    round(resultado.csll_retida, 2),
                "irrf_retido":    round(resultado.irrf_retido, 2),
                "juros":          round(resultado.total_juros, 2),
                "base_liquida":   round(resultado.cofins.base_calculo, 2),
            },
            "cofins": {
                "aliquota":       resultado.cofins.aliquota,
                "valor_apurado":  round(resultado.cofins.valor_apurado, 2),
                "retencao_fonte": round(resultado.cofins.retencao_fonte, 2),
                "valor_a_pagar":  round(resultado.cofins.valor_a_pagar, 2),
            },
            "pis": {
                "aliquota":       resultado.pis.aliquota,
                "valor_apurado":  round(resultado.pis.valor_apurado, 2),
                "retencao_fonte": round(resultado.pis.retencao_fonte, 2),
                "valor_a_pagar":  round(resultado.pis.valor_a_pagar, 2),
            },
            "alertas": [
                {
                    "tipo":        a.tipo,
                    "descricao":   a.descricao,
                    "quantidade":  a.quantidade,
                    "valor_total": round(a.valor_total, 2),
                    "nfs":         a.nfs,
                }
                for a in alertas
            ],
            "consolidacao": consolidacao,
        }

        # ── Verificação de duplicidade ──────────────────────────────────
        existing = _session_get_by_competencia(competencia)
        if existing:
            existing_res = existing.get("resultado") or existing.get("resultado", {})
            fp_new = _totais_fingerprint(resp)
            fp_old = _totais_fingerprint(existing_res)

            if fp_new == fp_old:
                # Dados idênticos — descarta o novo processamento
                existing_id = existing.get("id") or list(_sessions.keys())[-1]
                resp["session_id"]   = existing_id
                resp["duplicidade"]  = "identico"
                resp["aviso"]        = (
                    f"A competência {competencia} já estava cadastrada e "
                    "os dados são idênticos. Nenhuma atualização foi necessária."
                )
                return resp

            # Dados diferentes — atualiza
            old_id = existing.get("id") or list(_sessions.keys())[-1]
            _session_update(old_id, session_id, output_path, resp)
            resp["duplicidade"] = "atualizado"
            resp["aviso"] = (
                f"A competência {competencia} já existia com dados diferentes. "
                "O registro foi atualizado com os novos valores."
            )
            # Calcula diferenças para exibição
            diffs = {
                k: {"anterior": fp_old[k], "novo": fp_new[k]}
                for k in fp_new if fp_new[k] != fp_old[k]
            }
            resp["diferencas"] = diffs
            return resp

        # ── Novo registro ────────────────────────────────────────────────
        _session_save(session_id, output_path, resp)
        return resp

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.get("/ultimo-resultado")
async def ultimo_resultado():
    """Retorna o resultado mais recente sem autenticação (somente leitura)."""
    if _use_supabase():
        sb = _get_supabase()
        rows = sb.table("sessions").select("resultado,competencia,created_at,id") \
            .order("created_at", desc=True).limit(1).execute()
        if rows.data:
            r = rows.data[0]
            resultado = r["resultado"]
            resultado["session_id"] = r["id"]
            return resultado
    # Fallback local: último da memória
    if _sessions:
        last = list(_sessions.values())[-1]
        return last["resultado"]
    return None


# ── Gestão de Usuários ───────────────────────────────────────────────────────

@app.get("/usuarios", dependencies=[Depends(require_auth)])
async def listar_usuarios():
    if not _use_supabase():
        raise HTTPException(status_code=503, detail="Gestão de usuários requer Supabase.")
    sb = _get_supabase()
    rows = sb.table("users").select("id,username,full_name,active,created_at,last_login") \
        .order("created_at", desc=False).execute()
    return rows.data or []


@app.post("/usuarios", dependencies=[Depends(require_auth)])
async def criar_usuario(
    username:  str = Form(...),
    password:  str = Form(...),
    full_name: str = Form(default=""),
):
    if not _use_supabase():
        raise HTTPException(status_code=503, detail="Gestão de usuários requer Supabase.")
    if len(password) < 6:
        raise HTTPException(status_code=422, detail="Senha deve ter pelo menos 6 caracteres.")
    sb = _get_supabase()
    # Verifica duplicidade
    existing = sb.table("users").select("id").eq("username", username).execute()
    if existing.data:
        raise HTTPException(status_code=409, detail=f"Usuário '{username}' já existe.")
    # Gera hash bcrypt compatível com pgcrypto
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()
    result = sb.table("users").insert({
        "username":      username,
        "password_hash": pw_hash,
        "full_name":     full_name or None,
        "active":        True,
    }).execute()
    return {"ok": True, "username": username}


@app.patch("/usuarios/{username}", dependencies=[Depends(require_auth)])
async def atualizar_usuario(
    username:     str,
    active:       bool | None = Form(default=None),
    new_password: str | None  = Form(default=None),
    full_name:    str | None  = Form(default=None),
):
    if not _use_supabase():
        raise HTTPException(status_code=503, detail="Gestão de usuários requer Supabase.")
    sb = _get_supabase()
    patch: dict = {}
    if active is not None:
        patch["active"] = active
    if full_name is not None:
        patch["full_name"] = full_name
    if new_password:
        if len(new_password) < 6:
            raise HTTPException(status_code=422, detail="Senha deve ter pelo menos 6 caracteres.")
        patch["password_hash"] = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt(rounds=12)).decode()
    if not patch:
        raise HTTPException(status_code=422, detail="Nenhum campo para atualizar.")
    sb.table("users").update(patch).eq("username", username).execute()
    return {"ok": True}


@app.delete("/usuarios/{username}", dependencies=[Depends(require_auth)])
async def excluir_usuario(username: str, request: Request):
    if not _use_supabase():
        raise HTTPException(status_code=503, detail="Gestão de usuários requer Supabase.")
    # Impede auto-exclusão
    token = request.headers.get("X-Auth-Token", "")
    try:
        payload = json.loads(base64.b64decode(token.rsplit(".", 1)[0]))
        if payload.get("u") == username:
            raise HTTPException(status_code=400, detail="Não é possível excluir o próprio usuário logado.")
    except HTTPException:
        raise
    except Exception:
        pass
    sb = _get_supabase()
    sb.table("users").delete().eq("username", username).execute()
    return {"ok": True}


@app.get("/exportar/{session_id}", dependencies=[Depends(require_auth)])
async def exportar(session_id: str, request: Request):
    session = _session_get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")

    if _use_supabase():
        # Baixa do Supabase Storage e retorna como stream
        sb = _get_supabase()
        storage_path = session.get("storage_path")
        filename = session.get("output_filename", "apuracao.xlsx")
        if not storage_path:
            raise HTTPException(status_code=404, detail="Arquivo não encontrado no storage.")
        file_bytes = sb.storage.from_(SUPABASE_BUCKET).download(storage_path)
        return StreamingResponse(
            iter([file_bytes]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    else:
        path = session["output_path"]
        if not path.exists():
            raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
        return FileResponse(
            path=str(path),
            filename=path.name,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


# ── Helpers internos ──────────────────────────────────────────────────────────

def _safe_float(v) -> float:
    import math
    try:
        f = float(v)
        return 0.0 if (math.isnan(f) or math.isinf(f)) else round(f, 2)
    except (TypeError, ValueError):
        return 0.0


def _build_consolidacao(dados: dict) -> list[dict]:
    import pandas as pd

    base = dados["recebidas"].copy()
    for key, col in [
        ("cofins_ret", "cofins_retido"),
        ("pis_ret",    "pis_retido"),
        ("csll_ret",   "csll_retido"),
        ("irrf",       "irrf"),
        ("juros",      "juros"),
    ]:
        df = dados[key]
        if not df.empty:
            base = base.merge(df, on="nf", how="outer")

    for col in ["recebido", "cofins_retido", "pis_retido", "csll_retido", "irrf", "juros"]:
        if col in base.columns:
            base[col] = pd.to_numeric(base[col], errors="coerce").fillna(0.0)
        else:
            base[col] = 0.0

    if "cliente" not in base.columns:
        base["cliente"] = ""
    base["cliente"] = base["cliente"].fillna("").astype(str)
    base["nf"] = base["nf"].fillna("").astype(str)

    base["base_liquida"] = (
        base["recebido"] + base["cofins_retido"] + base["pis_retido"]
        + base["csll_retido"] + base["irrf"] - base["juros"]
    )
    base = base.sort_values("nf").reset_index(drop=True)

    return [
        {
            "nf":            str(row["nf"]),
            "cliente":       str(row["cliente"]),
            "recebido":      _safe_float(row["recebido"]),
            "cofins_retido": _safe_float(row["cofins_retido"]),
            "pis_retido":    _safe_float(row["pis_retido"]),
            "csll_retido":   _safe_float(row["csll_retido"]),
            "irrf":          _safe_float(row["irrf"]),
            "juros":         _safe_float(row["juros"]),
            "base_liquida":  _safe_float(row["base_liquida"]),
        }
        for _, row in base.iterrows()
    ]
