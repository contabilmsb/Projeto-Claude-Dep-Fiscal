"""
Consolidação das Retenções INSS: relaciona cada linha da planilha INSS
(uma retenção previdenciária) à respectiva nota fiscal, usando o número
do comprovante como chave — INSS."Comprovante" =
INSS Notas Fiscais."Comprovante".
"""

import pandas as pd

from .reader import COLS_INSS, COLS_NOTAS

COLUNAS_SAIDA = [
    "Código do Fornecedor",
    "Nome/Razão Social do Fornecedor",
    "CNPJ do Fornecedor",
    "Data do Arquivo INSS",
    "Número da Nota Fiscal",
    "SITE",
    "Código do Imposto Retido na Fonte",
    "Origem do Valor",
    "Valor do Imposto Retido na Fonte",
    "Comprovante",
]


def consolidar(df_inss: pd.DataFrame, df_notas: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    avisos = []

    notas_slim = df_notas[[
        COLS_NOTAS["comprovante"], COLS_NOTAS["numero_nf"], COLS_NOTAS["conta"],
        COLS_NOTAS["nome"], COLS_NOTAS["cnpj"], COLS_NOTAS["estabelecimento"],
    ]].rename(columns={
        COLS_NOTAS["comprovante"]: "_comprovante_nf",
        COLS_NOTAS["numero_nf"]: "Número da Nota Fiscal",
        COLS_NOTAS["conta"]: "Código do Fornecedor",
        COLS_NOTAS["nome"]: "Nome/Razão Social do Fornecedor",
        COLS_NOTAS["cnpj"]: "CNPJ do Fornecedor",
        COLS_NOTAS["estabelecimento"]: "SITE",
    })

    duplicados = notas_slim[notas_slim.duplicated("_comprovante_nf", keep=False)]
    if not duplicados.empty:
        for comp in sorted(duplicados["_comprovante_nf"].dropna().unique()):
            avisos.append(
                f"Comprovante {comp} aparece mais de uma vez na planilha de Notas Fiscais — "
                f"usada a primeira ocorrência."
            )
    notas_slim = notas_slim.drop_duplicates("_comprovante_nf", keep="first")

    merged = df_inss.merge(
        notas_slim, left_on=COLS_INSS["comprovante"], right_on="_comprovante_nf", how="left"
    )

    sem_nf = merged[merged["_comprovante_nf"].isna()]
    for comp in sorted(sem_nf[COLS_INSS["comprovante"]].dropna().unique()):
        avisos.append(
            f"Comprovante {comp}: não encontrado na planilha de Notas Fiscais — a planilha INSS não "
            f"traz o código do fornecedor, então essa linha ficou sem fornecedor identificado."
        )

    # A planilha INSS não tem uma coluna própria de conta de fornecedor,
    # por isso, sem NF correspondente, não há como identificar o fornecedor — usa um código
    # provisório baseado no comprovante para não perder o valor do total.
    codigo_fornecedor = merged["Código do Fornecedor"].fillna(
        "(SEM NF - " + merged[COLS_INSS["comprovante"]].astype(str) + ")"
    )

    saida = pd.DataFrame({
        "Código do Fornecedor": codigo_fornecedor,
        "Nome/Razão Social do Fornecedor": merged["Nome/Razão Social do Fornecedor"],
        "CNPJ do Fornecedor": merged["CNPJ do Fornecedor"],
        "Data do Arquivo INSS": merged[COLS_INSS["data"]],
        "Número da Nota Fiscal": merged["Número da Nota Fiscal"],
        "SITE": merged["SITE"],
        "Código do Imposto Retido na Fonte": merged[COLS_INSS["codigo_imposto"]],
        "Origem do Valor": merged[COLS_INSS["origem_valor"]],
        "Valor do Imposto Retido na Fonte": merged[COLS_INSS["valor_retido"]],
        "Comprovante": merged[COLS_INSS["comprovante"]],
    })

    return saida, avisos


def acumular_por_fornecedor(df_saida: pd.DataFrame) -> pd.DataFrame:
    """
    Resumo acumulado por fornecedor: soma o valor de INSS retido — sem o
    número da nota fiscal ou do comprovante, já que uma linha aqui pode
    somar vários comprovantes — e usa a data mais recente entre os
    lançamentos do fornecedor. Quando um mesmo fornecedor tem lançamentos
    em mais de um SITE (estabelecimento fiscal), os valores são
    desmembrados em uma linha por (fornecedor, SITE).
    """
    df = df_saida.copy()
    df["SITE"] = df["SITE"].fillna("(sem SITE)")

    agregado = (
        df.groupby(["Código do Fornecedor", "SITE", "Nome/Razão Social do Fornecedor", "CNPJ do Fornecedor"])
        .agg(**{
            "INSS Retido": ("Valor do Imposto Retido na Fonte", "sum"),
            "Data do Arquivo INSS (mais recente)": ("Data do Arquivo INSS", "max"),
        })
        .reset_index()
    )

    # A base de cálculo ("Origem do Valor") é somada uma única vez por
    # comprovante, para não contar em dobro caso um comprovante apareça
    # mais de uma vez na planilha.
    base_calculo = (
        df.drop_duplicates(["Código do Fornecedor", "SITE", "Comprovante"])
        .groupby(["Código do Fornecedor", "SITE"])["Origem do Valor"]
        .sum()
        .rename("Base de Cálculo")
    )
    agregado = agregado.merge(base_calculo, on=["Código do Fornecedor", "SITE"], how="left")

    colunas_finais = [
        "Código do Fornecedor", "SITE", "Nome/Razão Social do Fornecedor", "CNPJ do Fornecedor",
        "Data do Arquivo INSS (mais recente)", "Base de Cálculo", "INSS Retido",
    ]
    return agregado[colunas_finais].sort_values(["Código do Fornecedor", "SITE"]).reset_index(drop=True)
