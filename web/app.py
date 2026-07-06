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
import shutil
import tempfile
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

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
OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

COFINS_RATE = 0.03
PIS_RATE    = 0.0065

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


def _session_save(session_id: str, output_path: Path, resultado: dict):
    """Salva sessão localmente ou no Supabase."""
    if _use_supabase():
        sb = _get_supabase()
        # Faz upload do Excel para o Storage
        storage_path = f"{session_id}/{output_path.name}"
        with open(output_path, "rb") as f:
            sb.storage.from_(SUPABASE_BUCKET).upload(
                storage_path,
                f.read(),
                {"content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
            )
        # Salva metadados na tabela
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

@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = STATIC_DIR / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.post("/processar")
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

        output_path = out_dir / f"Apuração PIS COFINS {comp_fmt} {ts}.xlsx"

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
            "competencia": competencia,
            "session_id": session_id,
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

        _session_save(session_id, output_path, resp)
        return resp

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.get("/exportar/{session_id}")
async def exportar(session_id: str):
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
