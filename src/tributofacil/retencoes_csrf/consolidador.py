"""
Consolidação das Retenções CSRF: relaciona cada linha da planilha PCC
(uma retenção de COFINS/CSLL/PIS) à respectiva nota fiscal, usando o
número do comprovante como chave — PCC."Comprovante de fatura" =
PCC Notas Fiscais."Comprovante".
"""

import pandas as pd

from .reader import COLS_PCC, COLS_NOTAS, COLS_NATUREZA

COLUNAS_SAIDA = [
    "Código do Fornecedor",
    "Natureza",
    "Nome/Razão Social do Fornecedor",
    "CNPJ do Fornecedor",
    "Data do Arquivo PCC",
    "Número da Nota Fiscal",
    "SITE",
    "Código do Imposto Retido na Fonte",
    "Origem do Valor",
    "Valor do Imposto Retido na Fonte",
    "Comprovante",
    "Comprovante de Pagamento",
]

CODIGO_PARA_COLUNA = {
    "COFINS RET": "COFINS Retido",
    "CSLL RET": "CSLL Retido",
    "PIS RET": "PIS Retido",
}


def consolidar(df_pcc: pd.DataFrame, df_notas: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
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
        "SITE": merged["SITE"],
        "Código do Imposto Retido na Fonte": merged[COLS_PCC["codigo_imposto"]],
        "Origem do Valor": merged[COLS_PCC["origem_valor"]],
        "Valor do Imposto Retido na Fonte": merged[COLS_PCC["valor_retido"]],
        "Comprovante": merged[COLS_PCC["comprovante_fatura"]],
        "Comprovante de Pagamento": merged[COLS_PCC["comprovante_pagamento"]],
    })

    return saida, avisos


def adicionar_natureza(df: pd.DataFrame, df_natureza: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """
    Acrescenta a coluna "Natureza" (logo após "Código do Fornecedor"),
    relacionando pelo código do fornecedor — planilha Natureza."Conta de
    fornecedor" = "Código do Fornecedor" já presente em `df`.
    """
    avisos = []

    natureza_slim = df_natureza[[COLS_NATUREZA["conta_fornecedor"], COLS_NATUREZA["natureza"]]].rename(
        columns={COLS_NATUREZA["conta_fornecedor"]: "Código do Fornecedor", COLS_NATUREZA["natureza"]: "Natureza"}
    )
    duplicados = natureza_slim[natureza_slim.duplicated("Código do Fornecedor", keep=False)]
    if not duplicados.empty:
        for cod in sorted(duplicados["Código do Fornecedor"].dropna().unique()):
            avisos.append(
                f"Fornecedor {cod} aparece mais de uma vez na planilha Natureza — usada a primeira ocorrência."
            )
    natureza_slim = natureza_slim.drop_duplicates("Código do Fornecedor", keep="first")

    resultado = df.merge(natureza_slim, on="Código do Fornecedor", how="left")

    sem_natureza = resultado[resultado["Natureza"].isna()]["Código do Fornecedor"].dropna().unique()
    for cod in sorted(sem_natureza):
        avisos.append(f"Fornecedor {cod}: código de Natureza não encontrado na planilha Natureza.")

    colunas = list(resultado.columns)
    colunas.remove("Natureza")
    idx = colunas.index("Código do Fornecedor") + 1
    colunas.insert(idx, "Natureza")
    return resultado[colunas], avisos


def acumular_por_fornecedor(df_saida: pd.DataFrame) -> pd.DataFrame:
    """
    Resumo acumulado por fornecedor: soma os valores retidos de cada
    imposto (PIS/COFINS/CSLL) em colunas separadas — sem o número da nota
    fiscal ou do comprovante, já que uma linha aqui pode somar vários
    comprovantes — e usa a data mais recente entre os lançamentos do
    fornecedor. Quando um mesmo fornecedor tem lançamentos em mais de um
    SITE (estabelecimento fiscal), os valores são desmembrados em uma
    linha por (fornecedor, SITE), preservando essa granularidade mesmo
    sem exibir o número da nota fiscal.
    """
    df = df_saida.copy()
    df["_coluna_imposto"] = df["Código do Imposto Retido na Fonte"].map(CODIGO_PARA_COLUNA)
    df["_coluna_imposto"] = df["_coluna_imposto"].fillna(df["Código do Imposto Retido na Fonte"])
    df["SITE"] = df["SITE"].fillna("(sem SITE)")

    pivot = df.pivot_table(
        index=["Código do Fornecedor", "SITE", "Nome/Razão Social do Fornecedor", "CNPJ do Fornecedor"],
        columns="_coluna_imposto",
        values="Valor do Imposto Retido na Fonte",
        aggfunc="sum",
        fill_value=0.0,
    ).reset_index()
    pivot.columns.name = None

    for col in CODIGO_PARA_COLUNA.values():
        if col not in pivot.columns:
            pivot[col] = 0.0

    datas = (
        df.groupby(["Código do Fornecedor", "SITE"])["Data do Arquivo PCC"]
        .max()
        .rename("Data do Arquivo PCC (mais recente)")
    )
    pivot = pivot.merge(datas, on=["Código do Fornecedor", "SITE"], how="left")

    # A base de cálculo ("Origem do Valor") é a mesma para as 3 linhas de
    # imposto (COFINS/CSLL/PIS) de um mesmo comprovante — soma-se uma única
    # vez por comprovante para não triplicar o valor ao acumular.
    base_calculo = (
        df.drop_duplicates(["Código do Fornecedor", "SITE", "Comprovante"])
        .groupby(["Código do Fornecedor", "SITE"])["Origem do Valor"]
        .sum()
        .rename("Base de Cálculo")
    )
    pivot = pivot.merge(base_calculo, on=["Código do Fornecedor", "SITE"], how="left")

    pivot["Total Retido"] = pivot["COFINS Retido"] + pivot["CSLL Retido"] + pivot["PIS Retido"]

    colunas_finais = [
        "Código do Fornecedor", "SITE", "Nome/Razão Social do Fornecedor", "CNPJ do Fornecedor",
        "Data do Arquivo PCC (mais recente)", "Base de Cálculo",
        "COFINS Retido", "CSLL Retido", "PIS Retido", "Total Retido",
    ]
    return pivot[colunas_finais].sort_values(["Código do Fornecedor", "SITE"]).reset_index(drop=True)
