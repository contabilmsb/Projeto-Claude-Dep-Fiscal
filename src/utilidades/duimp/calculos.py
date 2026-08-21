"""
Cálculos derivados a partir dos dados extraídos da DUIMP:

  - Peso bruto: a DUIMP só informa o total do processo, nunca por item.
    Rateado por item proporcionalmente à participação de cada item no peso
    líquido total (base física — o peso da embalagem tende a acompanhar o
    peso do produto). É uma estimativa, não o valor exato por item.

  - Número da adição: a DUIMP também não indica, na página de cada item, a
    qual adição do Siscomex ele pertence — só o resumo agregado por adição
    aparece uma vez, no início do processo. Como pista, os itens são
    agrupados pelo fabricante/produtor (cada adição corresponde, nos casos
    observados, a um fabricante diferente) e a ordem dos grupos é associada
    à ordem das adições declaradas. É uma inferência, não um dado declarado
    por item — por isso sempre gera aviso.

Tributos e encargos (II, IPI, PIS, COFINS, frete, seguro, taxa Siscomex,
despesas aduaneiras) NÃO são rateados por item: são apresentados como estão
na DI, por adição/processo, na aba "Detalhes".
"""


def aplicar_rateio_peso_bruto(cabecalho: dict, itens: list[dict]) -> list[str]:
    """Adiciona a cada item (in place) o peso bruto rateado. Retorna avisos."""
    avisos = []
    total_peso_liquido = sum(it.get("peso_liquido_kg") or 0 for it in itens)
    peso_bruto_total = cabecalho.get("peso_bruto_total_kg")

    if not total_peso_liquido or peso_bruto_total is None:
        avisos.append(
            "Não foi possível localizar o peso líquido total ou o peso bruto total do processo — "
            "a coluna \"Peso Bruto Rateado\" ficou em branco."
        )
        for it in itens:
            it["peso_bruto_rateado_kg"] = None
        return avisos

    for it in itens:
        peso_liquido = it.get("peso_liquido_kg") or 0
        it["peso_bruto_rateado_kg"] = round(peso_liquido / total_peso_liquido * peso_bruto_total, 5)

    return avisos


def inferir_numero_adicao(cabecalho: dict, itens: list[dict]) -> list[str]:
    """Adiciona a cada item (in place) o número da adição inferido. Retorna avisos."""
    avisos = []
    adicoes = cabecalho.get("adicoes") or []

    grupos_ordem = []
    for it in itens:
        fab = it.get("fabricante_legal")
        if fab not in grupos_ordem:
            grupos_ordem.append(fab)

    if not adicoes or len(grupos_ordem) != len(adicoes):
        avisos.append(
            "Não foi possível inferir com segurança o número da adição de cada item (a quantidade "
            "de fabricantes distintos não corresponde à quantidade de adições do processo) — a "
            "coluna \"Número da Adição\" ficou em branco."
        )
        for it in itens:
            it["numero_adicao"] = None
        return avisos

    mapa_fabricante_para_adicao = {
        fab: adicoes[i]["numero"] for i, fab in enumerate(grupos_ordem)
    }
    for it in itens:
        it["numero_adicao"] = mapa_fabricante_para_adicao.get(it.get("fabricante_legal"))

    avisos.append(
        "A coluna \"Número da Adição\" é uma INFERÊNCIA: a DUIMP não declara essa informação por "
        "item, apenas o resumo agregado por adição. Os itens foram agrupados pelo fabricante/produtor "
        "e associados às adições na mesma ordem em que aparecem no processo — confira contra a DI "
        "antes de usar para fins fiscais."
    )
    return avisos
