"""
Leitura e normalização das planilhas fonte.
Cada função retorna um DataFrame já limpo com as colunas padronizadas.
"""

import re
import pandas as pd
from pathlib import Path


# ─── Utilitários ──────────────────────────────────────────────────────────────

def _extract_nf(text: str) -> str | None:
    """
    Extrai número de NF (9 dígitos) de um campo de descrição.
    Exemplo: 'Pagamento, cliente 05/05/2026 000018618 COB_BRA_...' → '000018618'
    """
    if pd.isna(text):
        return None
    m = re.search(r'\b(\d{9})\b', str(text))
    return m.group(1) if m else None


def _find_col(df: pd.DataFrame, *keywords: str) -> str:
    """Localiza coluna pelo nome, insensível a maiúsculas/espaços."""
    for col in df.columns:
        normalized = str(col).lower().strip()
        if all(kw.lower() in normalized for kw in keywords):
            return col
    raise KeyError(f"Coluna não encontrada com palavras-chave {keywords}. "
                   f"Colunas disponíveis: {list(df.columns)}")


# ─── Leitores específicos ─────────────────────────────────────────────────────

def load_recebidas(path: Path) -> pd.DataFrame:
    """
    Recebidas Clientes: pagamentos recebidos de clientes.
    Retorna: nf (str), recebido (float), cliente (str), data (object)
    """
    df = pd.read_excel(path, dtype=str)
    df.columns = df.columns.str.strip()

    desc_col  = _find_col(df, "descri")
    cred_col  = _find_col(df, "créd")
    nome_col  = _find_col(df, "nome")
    data_col  = _find_col(df, "data")

    df["nf"] = df[desc_col].apply(_extract_nf)
    df[cred_col] = pd.to_numeric(df[cred_col], errors="coerce").fillna(0)

    result = (
        df[df["nf"].notna()]
        [[desc_col, "nf", cred_col, nome_col, data_col]]
        .rename(columns={cred_col: "recebido", nome_col: "cliente", data_col: "data"})
    )
    return result.groupby("nf", as_index=False).agg(
        recebido=("recebido", "sum"),
        cliente=("cliente", "first"),
    )


def load_retencao(path: Path, coluna_valor: str) -> pd.DataFrame:
    """
    Lê planilha de retenção (COFINS, PIS, CSLL, IRRF).
    Retorna: nf (str), <coluna_valor> (float)

    Exclui lançamentos de ajuste de diário (Diário-razão) sem NF associada.
    Para o IRRF, também exclui o lançamento de encerramento do mês.
    """
    df = pd.read_excel(path, dtype=str)
    df.columns = df.columns.str.strip()

    desc_col = _find_col(df, "descri")
    val_col  = _find_col(df, "valor")

    # Quando há múltiplas colunas 'valor', prefere a sem 'moeda' / 'relatório'
    if isinstance(val_col, str):
        val_candidates = [c for c in df.columns
                          if "valor" in c.lower()
                          and "moeda" not in c.lower()
                          and "relat" not in c.lower()
                          and "exibi" not in c.lower()
                          and "transaç" not in c.lower()]
        if val_candidates:
            val_col = val_candidates[0]

    df["nf"] = df[desc_col].apply(_extract_nf)
    df[val_col] = pd.to_numeric(df[val_col], errors="coerce").fillna(0)

    result = df[df["nf"].notna()][["nf", val_col]].copy()
    result = result.rename(columns={val_col: coluna_valor})
    return result.groupby("nf", as_index=False).agg({coluna_valor: "sum"})


def load_juros(path: Path) -> pd.DataFrame:
    """
    Juros e multas recebidos de clientes.
    Retorna: nf (str), juros (float) — valores positivos.
    """
    df = pd.read_excel(path, dtype=str)
    df.columns = df.columns.str.strip()

    desc_col = _find_col(df, "descri")

    # Aceita colunas "Valor*" ou "Crédito" (mesmo formato do extrato bancário)
    val_col_candidates = [c for c in df.columns
                          if ("valor" in c.lower()
                              and "moeda" not in c.lower()
                              and "relat" not in c.lower()
                              and "exibi" not in c.lower()
                              and "transaç" not in c.lower())
                          or "créd" in c.lower()]
    if val_col_candidates:
        val_col = val_col_candidates[0]
    else:
        val_col = _find_col(df, "valor")

    df["nf"] = df[desc_col].apply(_extract_nf)
    df[val_col] = pd.to_numeric(df[val_col], errors="coerce").fillna(0).abs()

    result = df[df["nf"].notna()][["nf", val_col]].copy()
    result = result.rename(columns={val_col: "juros"})
    return result.groupby("nf", as_index=False).agg(juros=("juros", "sum"))


def load_vendas(path: Path) -> pd.DataFrame:
    """
    Notas fiscais emitidas (base accrual).
    Retorna: nf (str), valor_venda (float), cliente (str), estado (str)
    """
    df = pd.read_excel(path, dtype=str)
    df.columns = df.columns.str.strip()

    num_col    = _find_col(df, "número")
    val_col    = _find_col(df, "valor total")
    nome_col   = _find_col(df, "nome")
    estado_col = _find_col(df, "estado")

    df["nf"] = df[num_col].str.strip().str.zfill(9)
    df[val_col] = pd.to_numeric(df[val_col], errors="coerce").fillna(0)

    return (
        df[["nf", val_col, nome_col, estado_col]]
        .rename(columns={val_col: "valor_venda", nome_col: "cliente", estado_col: "estado"})
        .groupby("nf", as_index=False)
        .agg(valor_venda=("valor_venda", "sum"), cliente=("cliente", "first"), estado=("estado", "first"))
    )


def load_all(files: dict, estornos: list[str] | None = None) -> dict[str, pd.DataFrame]:
    """
    Carrega todos os arquivos fonte e retorna dicionário de DataFrames.

    Parâmetros
    ----------
    estornos : lista de NFs (9 dígitos) a excluir de todas as fontes antes do cálculo.
    """
    dados = {
        "recebidas":  load_recebidas(files["recebidas"]),
        "cofins_ret": load_retencao(files["cofins_ret"], "cofins_retido"),
        "pis_ret":    load_retencao(files["pis_ret"],    "pis_retido"),
        "csll_ret":   load_retencao(files["csll_ret"],   "csll_retido"),
        "irrf":       load_retencao(files["irrf"],       "irrf"),
        "juros":      load_juros(files["juros"]),
        "vendas":     load_vendas(files["vendas"]),
    }

    if estornos:
        nfs = set(estornos)
        for key in dados:
            df = dados[key]
            if "nf" in df.columns:
                dados[key] = df[~df["nf"].isin(nfs)].reset_index(drop=True)

    return dados
