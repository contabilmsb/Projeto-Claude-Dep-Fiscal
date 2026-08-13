"""
Leitura das planilhas de origem da apuração de Retenções INSS
(Contribuição Previdenciária Retida na Fonte sobre pagamentos a fornecedores).

Duas planilhas são necessárias:
  - INSS: uma linha por retenção de INSS de cada comprovante de pagamento.
  - INSS Notas Fiscais: uma linha por nota fiscal/comprovante, com os dados
    do fornecedor.

INSS e INSS Notas Fiscais se relacionam pelo número do comprovante: a coluna
"Comprovante" é comum às duas planilhas.
"""

import pandas as pd
from pathlib import Path

COLS_INSS = {
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


def _validar_colunas(df: pd.DataFrame, colunas: dict):
    faltantes = [v for v in colunas.values() if v not in df.columns]
    if faltantes:
        raise ValueError(
            f"colunas não encontradas: {', '.join(faltantes)}. "
            f"Colunas disponíveis: {', '.join(str(c) for c in df.columns)}"
        )


def load_inss(path: Path) -> pd.DataFrame:
    """Lê a planilha INSS (uma linha por retenção de INSS na fonte)."""
    df = pd.read_excel(path, sheet_name=0)
    _validar_colunas(df, COLS_INSS)
    return df


def load_notas(path: Path) -> pd.DataFrame:
    """Lê a planilha INSS Notas Fiscais (uma linha por comprovante/nota fiscal)."""
    df = pd.read_excel(path, sheet_name=0)
    _validar_colunas(df, COLS_NOTAS)
    return df
