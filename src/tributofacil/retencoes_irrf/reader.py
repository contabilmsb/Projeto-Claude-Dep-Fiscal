"""
Leitura das planilhas de origem da apuração de Retenções IRRF
(Imposto de Renda Retido na Fonte sobre pagamentos a fornecedores).

Três planilhas são necessárias:
  - IRRF: uma linha por retenção de IRRF de cada comprovante de pagamento.
  - IRRF Notas Fiscais: uma linha por nota fiscal/comprovante, com os dados
    do fornecedor.
  - Natureza: uma linha por fornecedor, com o código de natureza associado.

IRRF e IRRF Notas Fiscais se relacionam pelo número do comprovante: a coluna
"Comprovante" é comum às duas planilhas. A planilha Natureza se relaciona
com as demais pelo código do fornecedor ("Conta de fornecedor").
"""

import pandas as pd
from pathlib import Path

COLS_IRRF = {
    "comprovante": "Comprovante",
    "data": "Data",
    "codigo_imposto": "Código do imposto",
    "origem_valor": "Origem do valor",
    "valor_retido": "Valor real do imposto",
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


def load_irrf(path: Path) -> pd.DataFrame:
    """Lê a planilha IRRF (uma linha por retenção de IRRF na fonte)."""
    df = pd.read_excel(path, sheet_name=0)
    _validar_colunas(df, COLS_IRRF)
    return df


def load_notas(path: Path) -> pd.DataFrame:
    """Lê a planilha IRRF Notas Fiscais (uma linha por comprovante/nota fiscal)."""
    df = pd.read_excel(path, sheet_name=0)
    _validar_colunas(df, COLS_NOTAS)
    return df


def load_natureza(path: Path) -> pd.DataFrame:
    """Lê a planilha Natureza (código de natureza por fornecedor)."""
    df = pd.read_excel(path, sheet_name=0)
    _validar_colunas(df, COLS_NATUREZA)
    return df
