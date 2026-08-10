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
from dataclasses import asdict
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

from src.irpj_csll import readers as irpj_readers
from src.irpj_csll.calculator import (
    calcular_mes as irpj_calcular_mes,
    consolidar_trimestre as irpj_consolidar_trimestre,
    apurar_mes as irpj_apurar_mes,
    apurar_varios_meses as irpj_apurar_varios_meses,
    trimestre_de as irpj_trimestre_de,
    meses_do_trimestre as irpj_meses_do_trimestre,
    ComponenteMes as IrpjComponenteMes,
)
from src.irpj_csll.validator import validar_trimestre_completo
from src.irpj_csll.writer import atualizar_template as atualizar_template_irpj_csll

from src.tributofacil.difal_bahia.xml_parser import parse_nfe_xml
from src.tributofacil.difal_bahia.calculator import (
    calcular_difal_item,
    ALIQUOTA_INTERNA_BA,
    ALIQUOTA_INTERNA_CONVENIO_5291,
)
from src.tributofacil.retencoes_csrf.reader import load_pcc, load_notas
from src.tributofacil.retencoes_csrf.consolidador import (
    consolidar as consolidar_retencoes_csrf,
    acumular_por_fornecedor as acumular_retencoes_csrf,
)
from src.tributofacil.retencoes_csrf.writer import gerar_excel as gerar_excel_retencoes_csrf
from src.tributofacil.difal_bahia.writer import gerar_excel as gerar_excel_difal_bahia

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
    if _sessions:
        last = list(_sessions.values())[-1]
        return last["resultado"]
    return None


def _build_resumo_list() -> list:
    """Retorna lista de competências com totais (usado por rotas públicas e protegidas)."""
    def _resumo(res: dict, sid: str, comp, created) -> dict:
        totais = res.get("totais") or {}
        cofins = res.get("cofins") or {}
        pis    = res.get("pis") or {}
        return {
            "id":             sid,
            "competencia":    comp,
            "created_at":     created,
            "base_liquida":   totais.get("base_liquida") or 0,
            "cofins_a_pagar": cofins.get("valor_a_pagar") or 0,
            "pis_a_pagar":    pis.get("valor_a_pagar") or 0,
            "total_a_pagar":  (cofins.get("valor_a_pagar") or 0) + (pis.get("valor_a_pagar") or 0),
            "nf_count":       len(res.get("consolidacao") or []),
        }

    if _use_supabase():
        sb = _get_supabase()
        rows = sb.table("sessions") \
            .select("id,competencia,created_at,resultado") \
            .order("created_at", desc=True).execute()
        return [
            _resumo(r.get("resultado") or {}, r["id"], r["competencia"], r["created_at"])
            for r in (rows.data or [])
        ]
    return [
        _resumo(s["resultado"], sid, s["resultado"].get("competencia"), None)
        for sid, s in _sessions.items()
    ]


@app.get("/periodos")
async def listar_periodos_publico():
    """Lista competências com totais — sem autenticação (somente leitura)."""
    return _build_resumo_list()


@app.get("/sessoes", dependencies=[Depends(require_auth)])
async def listar_sessoes():
    """Lista todas as competências com resumo de totais (autenticado)."""
    return _build_resumo_list()


@app.get("/sessao/{session_id}", dependencies=[Depends(require_auth)])
async def get_sessao(session_id: str):
    """Retorna dados completos de uma sessão específica."""
    session = _session_get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")
    if _use_supabase():
        resultado = session.get("resultado", {})
        resultado["session_id"] = session.get("id", session_id)
        return resultado
    resultado = session["resultado"]
    resultado["session_id"] = session_id
    return resultado


@app.get("/consolidacao-todas", dependencies=[Depends(require_auth)])
async def consolidacao_todas():
    """Consolidação de NFs de todas as competências processadas, concatenadas."""
    if _use_supabase():
        sb = _get_supabase()
        rows = sb.table("sessions").select("competencia,resultado,created_at") \
            .order("created_at", desc=True).execute()
        sessoes = [
            (r["competencia"], r.get("resultado") or {})
            for r in (rows.data or [])
        ]
    else:
        sessoes = [
            (s["resultado"].get("competencia"), s["resultado"])
            for s in _sessions.values()
        ]

    todas_nfs = []
    todos_alertas = []
    for competencia, resultado in sessoes:
        for nf_row in resultado.get("consolidacao") or []:
            linha = dict(nf_row)
            linha["competencia"] = competencia
            todas_nfs.append(linha)
        for alerta in resultado.get("alertas") or []:
            a = dict(alerta)
            a["descricao"] = f"[{competencia}] {a.get('descricao', '')}"
            todos_alertas.append(a)

    return {
        "competencia": "Todas as competências",
        "consolidacao": todas_nfs,
        "alertas": todos_alertas,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Tributo Fácil — DIFAL de compras interestaduais destinadas à Bahia
#
# Módulo sem persistência: recebe os XMLs de NF-e, calcula o DIFAL item a
# item (Lei nº 7.014/1996) e devolve direto o Excel para download.
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/tributofacil/difal-bahia/processar", dependencies=[Depends(require_auth)])
async def tributofacil_difal_bahia_processar(arquivos: list[UploadFile] = File(...)):
    tmp_dir = Path(tempfile.mkdtemp(prefix="difal_bahia_"))
    try:
        linhas = []
        avisos = []
        for arquivo in arquivos:
            dest_path = tmp_dir / arquivo.filename
            dest_path.write_bytes(await arquivo.read())
            try:
                itens = parse_nfe_xml(dest_path, arquivo.filename)
            except Exception as e:
                avisos.append(f"{arquivo.filename}: erro ao ler o XML — {e}")
                continue

            if not itens:
                avisos.append(f"{arquivo.filename}: nenhum item (<det>) encontrado na NF-e.")

            for item in itens:
                if item.uf_destino != "BA":
                    avisos.append(
                        f"{arquivo.filename} (NF {item.numero_nf}): UF de destino é "
                        f"{item.uf_destino or '(vazio)'}, não BA — incluído mesmo assim, revisar."
                    )
                aliquota_interna = (
                    ALIQUOTA_INTERNA_CONVENIO_5291 if item.reducao_base_convenio_5291 else ALIQUOTA_INTERNA_BA
                )
                res = calcular_difal_item(
                    item.valor_operacao, item.aliquota_interestadual, item.substituicao_tributaria,
                    aliquota_interna=aliquota_interna,
                    aliquota_interestadual_referencia=item.aliquota_interestadual_referencia,
                )
                linhas.append((item, res))

        if not linhas:
            raise HTTPException(status_code=422, detail="Nenhum item válido encontrado nos arquivos enviados.")

        excel_bytes = gerar_excel_difal_bahia(linhas, avisos)
        total_difal = sum(res.difal for _, res in linhas)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"DIFAL_Bahia_{ts}.xlsx"

        return StreamingResponse(
            iter([excel_bytes]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Difal-Total": f"{total_difal:.2f}",
                "X-Difal-Qtd-Itens": str(len(linhas)),
                "X-Difal-Qtd-Avisos": str(len(avisos)),
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.post("/tributofacil/retencoes-csrf/processar", dependencies=[Depends(require_auth)])
async def tributofacil_retencoes_csrf_processar(
    pcc: UploadFile = File(...),
    notas_fiscais: UploadFile = File(...),
):
    tmp_dir = Path(tempfile.mkdtemp(prefix="retencoes_csrf_"))
    try:
        pcc_path = tmp_dir / pcc.filename
        pcc_path.write_bytes(await pcc.read())
        notas_path = tmp_dir / notas_fiscais.filename
        notas_path.write_bytes(await notas_fiscais.read())

        try:
            df_pcc = load_pcc(pcc_path)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Arquivo PCC ({pcc.filename}): {e}")
        try:
            df_notas = load_notas(notas_path)
        except Exception as e:
            raise HTTPException(
                status_code=422, detail=f"Arquivo PCC Notas Fiscais ({notas_fiscais.filename}): {e}"
            )

        df_saida, avisos = consolidar_retencoes_csrf(df_pcc, df_notas)
        if df_saida.empty:
            raise HTTPException(status_code=422, detail="Nenhum registro encontrado para consolidar.")
        df_acumulado = acumular_retencoes_csrf(df_saida)

        excel_bytes = gerar_excel_retencoes_csrf(df_saida, df_acumulado, avisos)
        total_retido = float(df_saida["Valor do Imposto Retido na Fonte"].fillna(0).sum())
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"Retencoes_CSRF_{ts}.xlsx"

        return StreamingResponse(
            iter([excel_bytes]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Csrf-Total": f"{total_retido:.2f}",
                "X-Csrf-Qtd-Linhas": str(len(df_saida)),
                "X-Csrf-Qtd-Avisos": str(len(avisos)),
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── Gestão de Usuários ───────────────────────────────────────────────────────

@app.get("/usuarios", dependencies=[Depends(require_auth)])
async def listar_usuarios():
    if not _use_supabase():
        raise HTTPException(status_code=503, detail="Gestão de usuários requer Supabase.")
    sb = _get_supabase()
    try:
        # Usa RPC SECURITY DEFINER para evitar restrições de permissão da chave anon
        result = sb.rpc("listar_usuarios_rpc", {}).execute()
        return result.data or []
    except Exception as e:
        if "does not exist" in str(e) or "Could not find" in str(e):
            raise HTTPException(
                status_code=503,
                detail="Função listar_usuarios_rpc não encontrada. Execute o supabase_users.sql no SQL Editor do Supabase (seção 7)."
            )
        raise HTTPException(status_code=500, detail=str(e))


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
    # Verifica duplicidade via RPC (SECURITY DEFINER)
    try:
        existing = sb.rpc("listar_usuarios_rpc", {}).execute()
        if any(u["username"] == username for u in (existing.data or [])):
            raise HTTPException(status_code=409, detail=f"Usuário '{username}' já existe.")
    except HTTPException:
        raise
    except Exception:
        pass  # Se RPC não existe ainda, deixa create_user_rpc detectar duplicidade
    # Hash bcrypt feito pelo pgcrypto via RPC
    try:
        sb.rpc("create_user_rpc", {
            "p_username":  username,
            "p_password":  password,
            "p_full_name": full_name or None,
        }).execute()
    except Exception as e:
        err_str = str(e)
        if "does not exist" in err_str or "Could not find" in err_str:
            raise HTTPException(
                status_code=503,
                detail="Função SQL não encontrada. Execute o arquivo supabase_users.sql no SQL Editor do Supabase (seção 5 — create_user_rpc)."
            )
        raise HTTPException(status_code=500, detail=err_str)
    return {"ok": True, "username": username}


@app.patch("/usuarios/{username}", dependencies=[Depends(require_auth)])
async def atualizar_usuario(
    username:     str,
    active:       str | None = Form(default=None),  # "true"/"false" via FormData
    new_password: str | None = Form(default=None),
    full_name:    str | None = Form(default=None),
):
    if not _use_supabase():
        raise HTTPException(status_code=503, detail="Gestão de usuários requer Supabase.")
    sb = _get_supabase()
    patch: dict = {}
    if active is not None:
        patch["active"] = active.lower() == "true"
    if full_name is not None:
        patch["full_name"] = full_name
    if new_password:
        if len(new_password) < 6:
            raise HTTPException(status_code=422, detail="Senha deve ter pelo menos 6 caracteres.")
        # Hash via RPC do Supabase
        try:
            sb.rpc("change_password_rpc", {
                "p_username":     username,
                "p_new_password": new_password,
            }).execute()
        except Exception as e:
            err_str = str(e)
            if "does not exist" in err_str or "Could not find" in err_str:
                raise HTTPException(status_code=503, detail="Função change_password_rpc não encontrada. Execute o supabase_users.sql no SQL Editor do Supabase.")
            raise HTTPException(status_code=500, detail=err_str)
    if patch:
        if "active" in patch:
            try:
                sb.rpc("toggle_usuario_rpc", {"p_username": username, "p_active": patch["active"]}).execute()
            except Exception:
                sb.table("users").update({"active": patch["active"]}).eq("username", username).execute()
        if "full_name" in patch:
            sb.table("users").update({"full_name": patch["full_name"]}).eq("username", username).execute()
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
    try:
        sb.rpc("excluir_usuario_rpc", {"p_username": username}).execute()
    except Exception:
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


# ══════════════════════════════════════════════════════════════════════════════
# Módulo IRPJ/CSLL — Lucro Presumido, apuração trimestral, base caixa
#
# Reaproveita da sessão PIS/COFINS da mesma competência: base_liquida,
# csll_retida, irrf_retido e juros (ver plano em .claude/plans, aprovado com
# o usuário). Cada mês é salvo isoladamente; ao completar os 3 meses de um
# trimestre-calendário, a consolidação trimestral é calculada automaticamente.
# ══════════════════════════════════════════════════════════════════════════════

SESSIONS_IRPJ_CSLL_TABLE = "sessions_irpj_csll"
_sessions_irpj_csll: dict[str, dict] = {}


def _irpj_session_get_by_competencia(competencia: str) -> dict | None:
    if _use_supabase():
        sb = _get_supabase()
        rows = sb.table(SESSIONS_IRPJ_CSLL_TABLE).select("*") \
            .eq("competencia", competencia) \
            .order("created_at", desc=True).limit(1).execute()
        return rows.data[0] if rows.data else None
    for sid, s in _sessions_irpj_csll.items():
        if s["resultado"].get("competencia") == competencia:
            return {**s, "id": sid}
    return None


def _irpj_session_delete(session_id: str):
    if _use_supabase():
        sb = _get_supabase()
        try:
            old = sb.table(SESSIONS_IRPJ_CSLL_TABLE).select("storage_path").eq("id", session_id).execute()
            if old.data and old.data[0].get("storage_path"):
                sb.storage.from_(SUPABASE_BUCKET).remove([old.data[0]["storage_path"]])
        except Exception:
            pass
        sb.table(SESSIONS_IRPJ_CSLL_TABLE).delete().eq("id", session_id).execute()
    else:
        _sessions_irpj_csll.pop(session_id, None)


def _irpj_session_save(session_id: str, output_path: Path | None, resultado: dict):
    if _use_supabase():
        sb = _get_supabase()
        storage_path = None
        filename = None
        if output_path:
            filename = output_path.name
            storage_path = f"irpj_csll/{session_id}/{filename}"
            with open(output_path, "rb") as f:
                sb.storage.from_(SUPABASE_BUCKET).upload(
                    storage_path, f.read(),
                    {"content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
                )
        sb.table(SESSIONS_IRPJ_CSLL_TABLE).insert({
            "id": session_id,
            "competencia": resultado["competencia"],
            "resultado": resultado,
            "storage_path": storage_path,
            "output_filename": filename,
        }).execute()
    else:
        _sessions_irpj_csll[session_id] = {"output_path": output_path, "resultado": resultado}


def _irpj_session_get(session_id: str) -> dict | None:
    if _use_supabase():
        sb = _get_supabase()
        rows = sb.table(SESSIONS_IRPJ_CSLL_TABLE).select("*").eq("id", session_id).execute()
        return rows.data[0] if rows.data else None
    return _sessions_irpj_csll.get(session_id)


def _irpj_build_resumo_list() -> list:
    def _resumo(res: dict, sid: str, comp, created) -> dict:
        c = res.get("componente") or {}
        return {
            "id": sid,
            "competencia": comp,
            "created_at": created,
            "revenda_base": c.get("revenda_base") or 0,
            "aplicacao_financeira": c.get("aplicacao_financeira") or 0,
            "variacao_cambial": c.get("variacao_cambial") or 0,
        }

    if _use_supabase():
        sb = _get_supabase()
        rows = sb.table(SESSIONS_IRPJ_CSLL_TABLE) \
            .select("id,competencia,created_at,resultado") \
            .order("created_at", desc=True).execute()
        return [
            _resumo(r.get("resultado") or {}, r["id"], r["competencia"], r["created_at"])
            for r in (rows.data or [])
        ]
    return [
        _resumo(s["resultado"], sid, s["resultado"].get("competencia"), None)
        for sid, s in _sessions_irpj_csll.items()
    ]


def _irpj_serializar_trimestre(resultado, session_id_excel: str | None = None) -> dict:
    return {
        "ano": resultado.ano,
        "trimestre": resultado.trimestre,
        "competencias": resultado.competencias,
        "irpj": asdict(resultado.irpj),
        "csll": asdict(resultado.csll),
        "parcelas_irpj": [asdict(p) for p in resultado.parcelas_irpj],
        "parcelas_csll": [asdict(p) for p in resultado.parcelas_csll],
        "session_id_excel": session_id_excel,
    }


def _irpj_tentar_consolidar_trimestre(ano: int, trimestre: int) -> dict | None:
    """Consolida o trimestre se as sessões dos 3 meses já existirem."""
    competencias = [f"{m:02d}/{ano}" for m in irpj_meses_do_trimestre(trimestre)]
    sessoes = [_irpj_session_get_by_competencia(c) for c in competencias]
    if not all(sessoes):
        return None
    componentes = [IrpjComponenteMes(**s["resultado"]["componente"]) for s in sessoes]
    resultado = irpj_consolidar_trimestre(ano, trimestre, componentes)
    session_id_excel = next(
        (s.get("id") for s in sessoes if s.get("storage_path") or s.get("output_path")),
        None,
    )
    return _irpj_serializar_trimestre(resultado, session_id_excel)


@app.post("/irpj-csll/processar", dependencies=[Depends(require_auth)])
async def irpj_csll_processar(
    competencia: str = Form(...),
    aplicacao_financeira: UploadFile = File(...),
    variacao_cambial: UploadFile = File(...),
    irrf: UploadFile = File(...),
    template: UploadFile | None = File(default=None),
):
    pis_cofins_session = _session_get_by_competencia(competencia)
    if not pis_cofins_session:
        raise HTTPException(
            status_code=422,
            detail=(
                f"A competência {competencia} ainda não foi processada no módulo "
                "PIS/COFINS. Processe-a primeiro naquele módulo — este cálculo "
                "reaproveita a base de cálculo, CSLL retida e juros de lá."
            ),
        )
    totais_pc = (pis_cofins_session.get("resultado") or {}).get("totais", {})

    mes, ano = _competencia_to_month_year(competencia)
    session_id = str(uuid.uuid4())
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"irpjcsll_{session_id}_"))

    try:
        file_map = {
            "aplicacao_financeira": aplicacao_financeira,
            "variacao_cambial": variacao_cambial,
            "irrf": irrf,
        }
        paths = {}
        for key, upload in file_map.items():
            dest = tmp_dir / upload.filename
            dest.write_bytes(await upload.read())
            paths[key] = dest

        valor_aplicacao = irpj_readers.load_aplicacao_financeira(paths["aplicacao_financeira"], mes, ano)
        valor_variacao = irpj_readers.load_variacao_cambial(paths["variacao_cambial"], mes, ano)
        valor_irrf_aplicacao = irpj_readers.load_irrf_aplicacao(paths["irrf"], mes, ano)

        componente = irpj_calcular_mes(
            competencia,
            revenda_base=totais_pc.get("base_liquida", 0.0),
            aplicacao_financeira=valor_aplicacao,
            variacao_cambial=valor_variacao,
            juros_recebidos=totais_pc.get("juros", 0.0),
            irrf_cliente=totais_pc.get("irrf_retido", 0.0),
            irrf_aplicacao=valor_irrf_aplicacao,
            csll_retida=totais_pc.get("csll_retida", 0.0),
        )

        resp = {
            "competencia": competencia,
            "session_id": session_id,
            "componente": asdict(componente),
        }

        trimestre = irpj_trimestre_de(mes)
        resp["trimestre_numero"] = trimestre
        resp["ano"] = ano
        resp["alertas"] = [
            a.__dict__ for a in
            validar_trimestre_completo(
                [f"{m:02d}/{ano}" for m in irpj_meses_do_trimestre(trimestre)
                 if _irpj_session_get_by_competencia(f"{m:02d}/{ano}") or f"{m:02d}/{ano}" == competencia],
                trimestre, ano,
            )
        ]

        # Upsert: substitui sessão existente da mesma competência e salva já
        # (sem Excel ainda) para que a checagem de trimestre completo abaixo
        # enxergue este mês junto com os outros dois.
        existente = _irpj_session_get_by_competencia(competencia)
        if existente:
            _irpj_session_delete(existente.get("id"))
        _irpj_session_save(session_id, None, resp)

        trimestre_consolidado = _irpj_tentar_consolidar_trimestre(ano, trimestre)
        if trimestre_consolidado:
            resp["trimestre"] = trimestre_consolidado

            if template is not None:
                template_dest = tmp_dir / template.filename
                template_dest.write_bytes(await template.read())

                competencias_trimestre = [f"{m:02d}/{ano}" for m in irpj_meses_do_trimestre(trimestre)]
                componentes = [
                    IrpjComponenteMes(**_irpj_session_get_by_competencia(c)["resultado"]["componente"])
                    for c in competencias_trimestre
                ]
                resultado_trimestre_obj = irpj_consolidar_trimestre(ano, trimestre, componentes)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                out_dir = Path(tempfile.gettempdir()) if _use_supabase() else OUTPUT_DIR
                safe_name = f"Apuracao_IRPJ_CSLL_{trimestre}T{ano}_{ts}.xlsx"
                try:
                    output_path = atualizar_template_irpj_csll(
                        template_path=template_dest,
                        output_path=out_dir / safe_name,
                        resultado=resultado_trimestre_obj,
                        meses=componentes,
                    )
                    # Re-salva esta sessão (a do último mês enviado) já com o Excel anexado
                    _irpj_session_delete(session_id)
                    _irpj_session_save(session_id, output_path, resp)
                except ValueError as e:
                    resp["alertas"].append({"tipo": "TEMPLATE", "descricao": str(e)})
        else:
            resp["trimestre"] = None

        return resp

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.get("/irpj-csll/periodos")
async def irpj_csll_periodos():
    """Lista competências (meses) processadas neste módulo — público, somente leitura."""
    return _irpj_build_resumo_list()


@app.get("/irpj-csll/ultimo-resultado")
async def irpj_csll_ultimo_resultado():
    """Retorna a competência mais recente do módulo IRPJ/CSLL sem autenticação (somente leitura)."""
    if _use_supabase():
        sb = _get_supabase()
        rows = sb.table(SESSIONS_IRPJ_CSLL_TABLE).select("resultado,competencia,created_at,id") \
            .order("created_at", desc=True).limit(1).execute()
        if not rows.data:
            return None
        r = rows.data[0]
        resultado = dict(r["resultado"])
        resultado["session_id"] = r["id"]
    elif _sessions_irpj_csll:
        last_id = list(_sessions_irpj_csll.keys())[-1]
        resultado = dict(_sessions_irpj_csll[last_id]["resultado"])
        resultado["session_id"] = last_id
    else:
        return None

    if resultado.get("componente"):
        componente = IrpjComponenteMes(**resultado["componente"])
        irpj_mes, csll_mes = irpj_apurar_mes(componente)
        resultado["apuracao_mes"] = {"irpj": asdict(irpj_mes), "csll": asdict(csll_mes)}
    return resultado


@app.get("/irpj-csll/todas")
async def irpj_csll_todas():
    """
    Soma os componentes de todas as competências já processadas e aplica a
    apuração informativa com o limite do adicional de IRPJ proporcional ao
    número de meses — público, somente leitura (mesma regra de
    /irpj-csll/ultimo-resultado).
    """
    if _use_supabase():
        sb = _get_supabase()
        rows = sb.table(SESSIONS_IRPJ_CSLL_TABLE).select("resultado").execute()
        resultados = [r["resultado"] for r in (rows.data or [])]
    else:
        resultados = [s["resultado"] for s in _sessions_irpj_csll.values()]

    componentes = [
        IrpjComponenteMes(**r["componente"]) for r in resultados if r.get("componente")
    ]
    if not componentes:
        raise HTTPException(status_code=404, detail="Nenhuma competência processada ainda.")

    irpj_total, csll_total = irpj_apurar_varios_meses(componentes)
    componente_soma = {
        "revenda_base": sum(c.revenda_base for c in componentes),
        "servicos_base": sum(c.servicos_base for c in componentes),
        "aplicacao_financeira": sum(c.aplicacao_financeira for c in componentes),
        "variacao_cambial": sum(c.variacao_cambial for c in componentes),
        "juros_recebidos": sum(c.juros_recebidos for c in componentes),
        "ganho_capital": sum(c.ganho_capital for c in componentes),
        "irrf_cliente": sum(c.irrf_cliente for c in componentes),
        "irrf_aplicacao": sum(c.irrf_aplicacao for c in componentes),
        "csll_retida": sum(c.csll_retida for c in componentes),
    }

    return {
        "competencia": f"Todas as competências ({len(componentes)})",
        "componente": componente_soma,
        "apuracao_mes": {"irpj": asdict(irpj_total), "csll": asdict(csll_total)},
    }


@app.get("/irpj-csll/trimestres")
async def irpj_csll_trimestres():
    """Lista trimestres com base nas competências processadas, indicando quais estão completos."""
    grupos: dict[tuple[int, int], set] = {}
    for r in _irpj_build_resumo_list():
        comp = r.get("competencia")
        if not comp:
            continue
        try:
            mes, ano = _competencia_to_month_year(comp)
        except Exception:
            continue
        chave = (ano, irpj_trimestre_de(mes))
        grupos.setdefault(chave, set()).add(comp)

    resultado = []
    for (ano, trimestre), competencias in grupos.items():
        esperadas = {f"{m:02d}/{ano}" for m in irpj_meses_do_trimestre(trimestre)}
        resultado.append({
            "ano": ano,
            "trimestre": trimestre,
            "competencias": sorted(competencias),
            "completo": esperadas.issubset(competencias),
        })
    resultado.sort(key=lambda r: (r["ano"], r["trimestre"]), reverse=True)
    return resultado


@app.get("/irpj-csll/sessao/{session_id}", dependencies=[Depends(require_auth)])
async def irpj_csll_get_sessao(session_id: str):
    session = _irpj_session_get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")
    resultado = session.get("resultado") or session.get("resultado", {})
    resultado["session_id"] = session.get("id", session_id)
    if resultado.get("componente"):
        componente = IrpjComponenteMes(**resultado["componente"])
        irpj_mes, csll_mes = irpj_apurar_mes(componente)
        resultado["apuracao_mes"] = {"irpj": asdict(irpj_mes), "csll": asdict(csll_mes)}
    return resultado


@app.get("/irpj-csll/trimestre/{ano}/{numero}")
async def irpj_csll_get_trimestre(ano: int, numero: int):
    resultado = _irpj_tentar_consolidar_trimestre(ano, numero)
    if not resultado:
        competencias = [f"{m:02d}/{ano}" for m in irpj_meses_do_trimestre(numero)]
        faltantes = [c for c in competencias if not _irpj_session_get_by_competencia(c)]
        raise HTTPException(
            status_code=404,
            detail=f"Trimestre incompleto — faltam as competências: {', '.join(faltantes)}",
        )
    return resultado


@app.get("/irpj-csll/exportar/{session_id}", dependencies=[Depends(require_auth)])
async def irpj_csll_exportar(session_id: str):
    session = _irpj_session_get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")

    if _use_supabase():
        sb = _get_supabase()
        storage_path = session.get("storage_path")
        filename = session.get("output_filename", "apuracao_irpj_csll.xlsx")
        if not storage_path:
            raise HTTPException(status_code=404, detail="Nenhum Excel gerado para esta sessão (envie o template para gerar).")
        file_bytes = sb.storage.from_(SUPABASE_BUCKET).download(storage_path)
        return StreamingResponse(
            iter([file_bytes]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    else:
        path = session.get("output_path")
        if not path or not Path(path).exists():
            raise HTTPException(status_code=404, detail="Nenhum Excel gerado para esta sessão (envie o template para gerar).")
        return FileResponse(
            path=str(path),
            filename=Path(path).name,
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
