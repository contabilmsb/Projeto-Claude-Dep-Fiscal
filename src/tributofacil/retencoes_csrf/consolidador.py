"""
Consolidação das Retenções CSRF: relaciona cada linha da planilha PCC
(uma retenção de COFINS/CSLL/PIS) à respectiva nota fiscal, usando o
número do comprovante como chave — PCC."Comprovante de fatura" =
PCC Notas Fiscais."Comprovante".
"""

import pandas as pd

from .reader import COLS_PCC, COLS_NOTAS

COLUNAS_SAIDA = [
    "Código do Fornecedor",
    "Nome/Razão Social do Fornecedor",
    "CNPJ do Fornecedor",
    "Data do Arquivo PCC",
    "Número da Nota Fiscal",
    "Código do Imposto Retido na Fonte",
    "Origem do Valor",
    "Valor do Imposto Retido na Fonte",
    "Comprovante",
    "Comprovante de Pagamento",
]


def consolidar(df_pcc: pd.DataFrame, df_notas: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    avisos = []

    notas_slim = df_notas[[
        COLS_NOTAS["comprovante"], COLS_NOTAS["numero_nf"], COLS_NOTAS["conta"],
        COLS_NOTAS["nome"], COLS_NOTAS["cnpj"],
    ]].rename(columns={
        COLS_NOTAS["comprovante"]: "_comprovante_nf",
        COLS_NOTAS["numero_nf"]: "Número da Nota Fiscal",
        COLS_NOTAS["conta"]: "Código do Fornecedor",
        COLS_NOTAS["nome"]: "Nome/Razão Social do Fornecedor",
        COLS_NOTAS["cnpj"]: "CNPJ do Fornecedor",
    })

    duplicados = notas_slim[notas_slim.duplicated("_comprovante_nf", keep=False)]
    if not duplicados.empty:
        for comp in sorted(duplicados["_comprovante_nf"].dropna().unique()):
            avisos.append(
                f"Comprovante {comp} aparece mais de uma vez na planilha de Notas Fiscais — "
                f"usada a primeira ocorrência."
            )
    notas_slim = notas_slim.drop_duplicates("_comprovante_nf", keep="first")

    merged = df_pcc.merge(
        notas_slim, left_on=COLS_PCC["comprovante_fatura"], right_on="_comprovante_nf", how="left"
    )

    sem_nf = merged[merged["_comprovante_nf"].isna()]
    for comp in sorted(sem_nf[COLS_PCC["comprovante_fatura"]].dropna().unique()):
        avisos.append(
            f"Comprovante {comp}: não encontrado na planilha de Notas Fiscais — linha incluída "
            f"sem dados de nota fiscal (código do fornecedor usado direto da planilha PCC)."
        )

    # Sem NF correspondente, usa a conta de fornecedor já presente na própria PCC.
    codigo_fornecedor = merged["Código do Fornecedor"].fillna(merged[COLS_PCC["conta_fornecedor"]])

    saida = pd.DataFrame({
        "Código do Fornecedor": codigo_fornecedor,
        "Nome/Razão Social do Fornecedor": merged["Nome/Razão Social do Fornecedor"],
        "CNPJ do Fornecedor": merged["CNPJ do Fornecedor"],
        "Data do Arquivo PCC": merged[COLS_PCC["data"]],
        "Número da Nota Fiscal": merged["Número da Nota Fiscal"],
        "Código do Imposto Retido na Fonte": merged[COLS_PCC["codigo_imposto"]],
        "Origem do Valor": merged[COLS_PCC["origem_valor"]],
        "Valor do Imposto Retido na Fonte": merged[COLS_PCC["valor_retido"]],
        "Comprovante": merged[COLS_PCC["comprovante_fatura"]],
        "Comprovante de Pagamento": merged[COLS_PCC["comprovante_pagamento"]],
    })

    return saida, avisos
