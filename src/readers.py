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

    Quando a NF aparece sem os zeros à esquerda (ex: 'PGTO NF 13243 COM IR...'),
    usa como alternativa o número que segue o literal 'NF', completando com
    zeros à esquerda até 9 dígitos — mesma convenção usada em load_vendas.
    """
    if pd.isna(text):
        return None
    text = str(text)
    m = re.search(r'\b(\d{9})\b', text)
    if m:
        return m.group(1)
    m = re.search(r'\bNF\.?\s*(\d+)\b', text, re.IGNORECASE)
    return m.group(1).zfill(9) if m else None


def _find_col(df: pd.DataFrame, *keywords: str) -> str:
    """Localiza coluna pelo nome, insensível a maiúsculas/espaços."""
    for col in df.columns:
        normalized = str(col).lower().strip()
        if all(kw.lower() in normalized for kw in keywords):
            return col
    raise KeyError(f"Coluna não encontrada com palavras-chave {keywords}. "
                   f"Colunas disponíveis: {list(df.columns)}")


def _find_col_optional(df: pd.DataFrame, *keywords: str) -> str | None:
    """Como _find_col, mas retorna None em vez de lançar erro quando não encontrada."""
    try:
        return _find_col(df, *keywords)
    except KeyError:
        return None


def _find_col_prefer_exact(df: pd.DataFrame, keyword: str) -> str:
    """
    Localiza coluna cujo nome normalizado seja EXATAMENTE `keyword`; se não houver,
    cai para a busca por substring (_find_col). Evita pegar a coluna errada quando
    o arquivo tem várias colunas contendo a palavra-chave (ex.: "Data", "Data Valor").
    """
    kw = keyword.lower().strip()
    for col in df.columns:
        if str(col).lower().strip() == kw:
            return col
    return _find_col(df, keyword)


_EXCEL_EPOCH = pd.Timestamp("1899-12-30")


def _parse_data_col(series: pd.Series, dayfirst: bool = False) -> pd.Series:
    """
    Converte a coluna Data (datetime já parseado pelo pandas, texto, ou serial
    Excel em texto).

    `dayfirst` deve refletir o formato de texto do arquivo de origem quando a
    data não vier como célula de data nativa do Excel:
      - Extratos/razão contábil (Recebidas, IRRF, COFINS/PIS/CSLL Retido) usam
        texto no formato mm/dd/aaaa (EUA) → dayfirst=False (padrão).
      - Arquivo de Vendas ("Data de Lançamento") usa texto no formato
        brasileiro dd/mm/aaaa → o chamador passa dayfirst=True.
    """
    parsed = pd.to_datetime(series, errors="coerce", dayfirst=dayfirst)
    ainda_vazio = parsed.isna()
    if ainda_vazio.any():
        serial = pd.to_numeric(series[ainda_vazio], errors="coerce")
        parsed.loc[ainda_vazio] = _EXCEL_EPOCH + pd.to_timedelta(serial, unit="D")
    return parsed


# ─── Leitores específicos ─────────────────────────────────────────────────────

def load_recebidas(path: Path) -> pd.DataFrame:
    """
    Recebidas Clientes: pagamentos recebidos de clientes.
    Retorna: nf (str), recebido (float), cliente (str), data (str dd/mm/aaaa)
    """
    df = pd.read_excel(path, dtype=str)
    df.columns = df.columns.str.strip()

    desc_col  = _find_col(df, "descri")
    cred_col  = _find_col(df, "créd")
    nome_col  = _find_col(df, "nome")
    data_col  = _find_col_prefer_exact(df, "data")

    df["nf"] = df[desc_col].apply(_extract_nf)
    df[cred_col] = pd.to_numeric(df[cred_col], errors="coerce").fillna(0)
    df["data"] = _parse_data_col(df[data_col])

    result = (
        df[df["nf"].notna()]
        [[desc_col, "nf", cred_col, nome_col, "data"]]
        .rename(columns={cred_col: "recebido", nome_col: "cliente"})
    )
    agregado = result.groupby("nf", as_index=False).agg(
        recebido=("recebido", "sum"),
        cliente=("cliente", "first"),
        data=("data", "max"),
    )
    agregado["data"] = agregado["data"].dt.strftime("%d/%m/%Y")
    return agregado


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
    Retorna: nf (str), valor_venda (float), cliente (str), estado (str),
             data_emissao (str dd/mm/aaaa) — data de lançamento da NF, quando disponível.
    """
    df = pd.read_excel(path, dtype=str)
    df.columns = df.columns.str.strip()

    num_col    = _find_col(df, "número")
    val_col    = _find_col(df, "valor total")
    nome_col   = _find_col(df, "nome")
    estado_col = _find_col(df, "estado")
    data_col   = _find_col_optional(df, "lan")  # "Data de Lançamento" / "Lancamento"

    df["nf"] = df[num_col].str.strip().str.zfill(9)
    df[val_col] = pd.to_numeric(df[val_col], errors="coerce").fillna(0)
    df["data_emissao"] = _parse_data_col(df[data_col], dayfirst=True) if data_col is not None else pd.NaT

    agregado = (
        df[["nf", val_col, nome_col, estado_col, "data_emissao"]]
        .rename(columns={val_col: "valor_venda", nome_col: "cliente", estado_col: "estado"})
        .groupby("nf", as_index=False)
        .agg(
            valor_venda=("valor_venda", "sum"),
            cliente=("cliente", "first"),
            estado=("estado", "first"),
            data_emissao=("data_emissao", "min"),
        )
    )
    agregado["data_emissao"] = agregado["data_emissao"].dt.strftime("%d/%m/%Y")
    return agregado


def load_all(files: dict, estornos: list[str] | None = None) -> dict[str, pd.DataFrame]:
    """
    Carrega todos os arquivos fonte e retorna dicionário de DataFrames.

    Parâmetros
    ----------
    estornos : lista de NFs (9 dígitos) a excluir de todas as fontes antes do cálculo.
    """
    carregadores = {
        "recebidas":  lambda: load_recebidas(files["recebidas"]),
        "cofins_ret": lambda: load_retencao(files["cofins_ret"], "cofins_retido"),
        "pis_ret":    lambda: load_retencao(files["pis_ret"],    "pis_retido"),
        "csll_ret":   lambda: load_retencao(files["csll_ret"],   "csll_retido"),
        "irrf":       lambda: load_retencao(files["irrf"],       "irrf"),
        "juros":      lambda: load_juros(files["juros"]),
        "vendas":     lambda: load_vendas(files["vendas"]),
    }
    labels = {
        "recebidas": "Recebidas", "cofins_ret": "COFINS Retido", "pis_ret": "PIS Retido",
        "csll_ret": "CSLL Retida", "irrf": "IRRF", "juros": "Juros Recebidos", "vendas": "Vendas",
    }
    dados = {}
    for key, carregar in carregadores.items():
        try:
            dados[key] = carregar()
        except Exception as e:
            nome_arquivo = Path(files[key]).name
            raise ValueError(f"Arquivo {labels[key]} ({nome_arquivo}): {e}") from e

    if estornos:
        nfs = set(estornos)
        for key in dados:
            df = dados[key]
            if "nf" in df.columns:
                dados[key] = df[~df["nf"].isin(nfs)].reset_index(drop=True)

    return dados
