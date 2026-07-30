"""
Leitura das planilhas fonte específicas do módulo IRPJ/CSLL:
  - Aplicação Financeira (receita)
  - Variação Cambial Ativa (receita)
  - IRRF (retenção sobre aplicações financeiras — extraída do arquivo de IRRF,
    que também traz retenções sobre pagamentos de clientes já reaproveitadas
    do módulo PIS/COFINS e por isso são ignoradas aqui)

Os arquivos são exportações do razão contábil (mesmo layout usado no módulo
PIS/COFINS: colunas "Descrição", "Data", "Valor"), mas os valores de receita
vêm com sinal de crédito (negativo) — por isso o valor absoluto é usado.

Os arquivos podem conter mais de um mês (ex.: exportações semestrais); por
segurança, todas as funções filtram pela coluna "Data" para a competência
informada, mesmo que a convenção passe a ser um arquivo por mês.
"""

import re
import pandas as pd
from pathlib import Path

from src.readers import _find_col, _extract_nf


_EXCEL_EPOCH = pd.Timestamp("1899-12-30")


def _parse_data_col(series: pd.Series) -> pd.Series:
    """Converte a coluna Data (datetime já parseado pelo pandas, ou serial Excel em texto)."""
    parsed = pd.to_datetime(series, errors="coerce")
    ainda_vazio = parsed.isna()
    if ainda_vazio.any():
        serial = pd.to_numeric(series[ainda_vazio], errors="coerce")
        parsed.loc[ainda_vazio] = _EXCEL_EPOCH + pd.to_timedelta(serial, unit="D")
    return parsed


def _load_receita_financeira(path: Path, mes: int, ano: int) -> float:
    """
    Lê planilha de receita financeira (Aplicação Financeira ou Variação Cambial
    Ativa) e retorna a soma em valor absoluto para o mês/ano informado.
    """
    df = pd.read_excel(path, dtype=str)
    df.columns = df.columns.str.strip()

    data_col = _find_col(df, "data")
    val_col_candidates = [
        c for c in df.columns
        if "valor" in c.lower()
        and "moeda" not in c.lower()
        and "relat" not in c.lower()
        and "exibi" not in c.lower()
        and "transaç" not in c.lower()
    ]
    val_col = val_col_candidates[0] if val_col_candidates else _find_col(df, "valor")

    datas = _parse_data_col(df[data_col])
    valores = pd.to_numeric(df[val_col], errors="coerce").fillna(0.0)

    mask = (datas.dt.month == mes) & (datas.dt.year == ano)
    return float(valores[mask].abs().sum())


def load_aplicacao_financeira(path: Path, mes: int, ano: int) -> float:
    """Receita de aplicação financeira do mês (inclusão integral na base IRPJ/CSLL)."""
    return _load_receita_financeira(path, mes, ano)


def load_variacao_cambial(path: Path, mes: int, ano: int) -> float:
    """Variação cambial ativa do mês (inclusão integral na base IRPJ/CSLL)."""
    return _load_receita_financeira(path, mes, ano)


def load_irrf_aplicacao(path: Path, mes: int, ano: int) -> float:
    """
    Lê a planilha de IRRF e retorna a soma das retenções que NÃO são sobre
    pagamento de cliente (ex.: "IR BB APLICAÇÃO 30/04/26", "IR RESGATE XP") —
    ou seja, tudo que não tem um número de NF reconhecível na descrição.

    Retenções sobre pagamentos de clientes (ex.: "Pagamento, cliente ...
    000018789 ...", com NF de 9 dígitos ou "NF <número>") são ignoradas aqui —
    já são reaproveitadas do módulo PIS/COFINS (campo irrf_retido da sessão
    do mês). Usar o mesmo reconhecimento de NF do módulo PIS/COFINS (em vez
    de uma palavra-chave como "APLICA") evita perder lançamentos com outras
    descrições (ex.: resgates de fundos/corretoras) que também não são
    retenção de cliente.
    """
    df = pd.read_excel(path, dtype=str)
    df.columns = df.columns.str.strip()

    desc_col = _find_col(df, "descri")
    data_col = _find_col(df, "data")
    val_col_candidates = [
        c for c in df.columns
        if "valor" in c.lower()
        and "moeda" not in c.lower()
        and "relat" not in c.lower()
        and "exibi" not in c.lower()
        and "transaç" not in c.lower()
    ]
    val_col = val_col_candidates[0] if val_col_candidates else _find_col(df, "valor")

    datas = _parse_data_col(df[data_col])
    valores = pd.to_numeric(df[val_col], errors="coerce").fillna(0.0)
    eh_pagamento_cliente = df[desc_col].apply(_extract_nf).notna()

    mask = (datas.dt.month == mes) & (datas.dt.year == ano) & ~eh_pagamento_cliente
    return float(valores[mask].sum())
