"""
Leitura das planilhas de origem da apuração de Retenções CSRF
(COFINS/CSLL/PIS retidos na fonte sobre pagamentos a fornecedores).

Três planilhas são necessárias:
  - PCC: uma linha por retenção (COFINS RET / CSLL RET / PIS RET) de cada
    comprovante de pagamento.
  - PCC Notas Fiscais: uma linha por nota fiscal/comprovante, com os dados
    do fornecedor.
  - Natureza: uma linha por fornecedor, com o código de natureza associado.

PCC e PCC Notas Fiscais se relacionam pelo número do comprovante: a coluna
"Comprovante de fatura" da planilha PCC corresponde à coluna "Comprovante"
da planilha de Notas Fiscais. A planilha Natureza se relaciona com as
demais pelo código do fornecedor ("Conta de fornecedor").
"""

import pandas as pd
from pathlib import Path

COLS_PCC = {
    "comprovante_pagamento": "Comprovante de pagamento",
    "comprovante_fatura": "Comprovante de fatura",
    "conta_fornecedor": "Conta de fornecedor",
    "data": "Data",
    "codigo_imposto": "Código de imposto retido na fonte",
    "moeda": "Moeda do pagamento",
    "descricao": "Descrição",
    "origem_valor": "Origem do valor",
    "valor_retido": "Imposto retido na fonte na moeda do pagamento",
}

COLS_NOTAS = {
    "comprovante": "Comprovante",
    "numero_nf": "Número",
    "conta": "Conta",
    "nome": "Nome",
    "cnpj": "CNPJ/CPF",
    "data_documento": "Data do documento",
    "valor_total": "Valor total",
    "descricao_operacao": "Descrição da operação",
    "estabelecimento": "ID do estabelecimento fiscal",
}

COLS_NATUREZA = {
    "conta_fornecedor": "Conta de fornecedor",
    "natureza": "Natureza",
}


def _validar_colunas(df: pd.DataFrame, colunas: dict):
    faltantes = [v for v in colunas.values() if v not in df.columns]
    if faltantes:
        raise ValueError(
            f"colunas não encontradas: {', '.join(faltantes)}. "
            f"Colunas disponíveis: {', '.join(str(c) for c in df.columns)}"
        )


def load_pcc(path: Path) -> pd.DataFrame:
    """Lê a planilha PCC (uma linha por retenção de COFINS/CSLL/PIS na fonte)."""
    df = pd.read_excel(path, sheet_name=0)
    _validar_colunas(df, COLS_PCC)
    return df


def load_notas(path: Path) -> pd.DataFrame:
    """Lê a planilha PCC Notas Fiscais (uma linha por comprovante/nota fiscal)."""
    df = pd.read_excel(path, sheet_name=0)
    _validar_colunas(df, COLS_NOTAS)
    return df


def load_natureza(path: Path) -> pd.DataFrame:
    """Lê a planilha Natureza (código de natureza por fornecedor)."""
    df = pd.read_excel(path, sheet_name=0)
    _validar_colunas(df, COLS_NATUREZA)
    return df
