"""
Rateio dos valores que a DUIMP só informa de forma agregada (por processo ou
por adição), nunca por item individual:

  - Peso bruto: só o total do processo é informado. Rateado por item
    proporcionalmente à participação de cada item no peso líquido total
    (base física — o peso da embalagem tende a acompanhar o peso do produto).
  - Valor aduaneiro e tributos (II, IPI, PIS, COFINS): informados por adição
    do Siscomex, não por item. Rateados por item proporcionalmente à
    participação de cada item no valor total na condição de venda (base de
    valor — é a convenção usual de rateio de frete/seguro/tributos aduaneiros).

Isso é uma estimativa, não o valor exato apurado pela Receita Federal por
item — está claramente identificado como "rateado" nas colunas da planilha.
"""


def aplicar_rateios(cabecalho: dict, itens: list[dict]) -> list[str]:
    """Adiciona aos itens (in place) os campos rateados. Retorna avisos."""
    avisos = []

    total_peso_liquido = sum(it.get("peso_liquido_kg") or 0 for it in itens)
    total_valor_venda = sum(it.get("valor_total_venda") or 0 for it in itens)

    peso_bruto_total = cabecalho.get("peso_bruto_total_kg")
    valor_aduaneiro_total = cabecalho.get("valor_aduaneiro_brl")

    adicoes = cabecalho.get("adicoes") or []
    total_ii = sum(a.get("ii_valor") or 0 for a in adicoes)
    total_ipi = sum(a.get("ipi_valor") or 0 for a in adicoes)
    total_pis = sum(a.get("pis_valor") or 0 for a in adicoes)
    total_cofins = sum(a.get("cofins_valor") or 0 for a in adicoes)

    if not adicoes:
        avisos.append(
            "Não foi possível localizar o resumo de tributos por adição no PDF — as colunas de "
            "II/IPI/PIS/COFINS rateado ficaram em branco."
        )

    for it in itens:
        peso_liquido = it.get("peso_liquido_kg") or 0
        valor_venda = it.get("valor_total_venda") or 0

        it["peso_bruto_rateado_kg"] = (
            round(peso_liquido / total_peso_liquido * peso_bruto_total, 5)
            if total_peso_liquido and peso_bruto_total is not None else None
        )

        participacao_valor = valor_venda / total_valor_venda if total_valor_venda else 0

        it["valor_aduaneiro_rateado_brl"] = (
            round(participacao_valor * valor_aduaneiro_total, 2)
            if valor_aduaneiro_total is not None else None
        )
        it["ii_rateado_brl"] = round(participacao_valor * total_ii, 2) if adicoes else None
        it["ipi_rateado_brl"] = round(participacao_valor * total_ipi, 2) if adicoes else None
        it["pis_rateado_brl"] = round(participacao_valor * total_pis, 2) if adicoes else None
        it["cofins_rateado_brl"] = round(participacao_valor * total_cofins, 2) if adicoes else None

    return avisos
