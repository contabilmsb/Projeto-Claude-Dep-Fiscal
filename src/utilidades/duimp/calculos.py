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

  - Taxa Siscomex: alguns formatos de extrato declaram o valor já por
    adição; outros só trazem o total do processo. Quando falta o valor por
    adição, é rateado entre as adições pela participação de cada uma na
    Base de Cálculo PIS/COFINS. Depois, dentro de cada adição, o valor é
    rateado por item pela participação de cada um no valor comercial total
    da adição (mesma lógica de rateio de custo de processo por valor).

  - Data de Vencimento: não é um campo da DUIMP — é calculada a partir da
    Data de Fabricação + Prazo de Validade de cada item (quando o prazo é
    determinado; "INDETERMINADA/INDETERMINADO" não gera vencimento).

Tributos e encargos (II, IPI, PIS, COFINS, frete, seguro, despesas
aduaneiras) NÃO são rateados por item: são apresentados como estão na DI,
por adição/processo, na aba "Detalhes". A Taxa Siscomex é a exceção, a
pedido do usuário, por ser útil no custeio de cada produto.
"""

import re

import pandas as pd


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
    """
    Adiciona a cada item (in place) o número da adição inferido. Retorna avisos.

    A inferência usa o NCM como sinal primário: cada item é comparado ao
    NCM de cada adição do processo (mesmo campo, presente nos dois). Quando
    o NCM do item corresponde a uma única adição, a associação é direta.
    Quando corresponde a mais de uma adição (mesmo NCM declarado em
    adições diferentes — comum quando fabricantes/fornecedores diferentes
    do mesmo produto foram agrupados em adições separadas), o desempate
    usa o fabricante/produtor do item, na ordem em que aparecem no
    processo, associado à ordem das adições daquele NCM.
    """
    avisos = []
    adicoes = cabecalho.get("adicoes") or []
    for it in itens:
        it["numero_adicao"] = None

    if not adicoes:
        avisos.append(
            "A DI não traz o resumo por adição — a coluna \"Número da Adição\" ficou em branco."
        )
        return avisos

    def normaliza_ncm(ncm):
        # Extrai só os 8 dígitos do código NCM do começo do campo,
        # tolerando qualquer pontuação entre eles ("90183929",
        # "9018.3929" ou "9018.39.29" — os três formatos já observados
        # em extratos reais). O campo do item costuma trazer a
        # descrição da posição junto (ex.: "8466.9100 - -- PARA
        # MÁQUINAS DA POSIÇÃO 84.64"), que tem outros números e não
        # pode ser incluída na comparação — por isso o limite de
        # exatamente 8 dígitos, parando aí.
        m = re.match(r"\s*((?:\d\.?){8})", ncm or "")
        return re.sub(r"\D", "", m.group(1)) if m else ""

    adicoes_por_ncm: dict = {}
    for a in adicoes:
        adicoes_por_ncm.setdefault(normaliza_ncm(a.get("ncm")), []).append(a)

    itens_por_ncm: dict = {}
    for it in itens:
        itens_por_ncm.setdefault(normaliza_ncm(it.get("ncm")), []).append(it)

    algum_ambiguo_resolvido = False
    algum_nao_resolvido = False

    for ncm, grupo_itens in itens_por_ncm.items():
        candidatas = adicoes_por_ncm.get(ncm) or []

        if len(candidatas) == 1:
            for it in grupo_itens:
                it["numero_adicao"] = candidatas[0]["numero"]
            continue

        if not candidatas:
            algum_nao_resolvido = True
            continue

        # NCM presente em mais de uma adição — desempata por
        # fabricante/produtor, na ordem em que os itens aparecem.
        fabricantes_ordem = []
        for it in grupo_itens:
            fab = it.get("fabricante_legal")
            if fab and fab not in fabricantes_ordem:
                fabricantes_ordem.append(fab)

        if fabricantes_ordem and len(fabricantes_ordem) == len(candidatas):
            mapa = {fab: candidatas[i]["numero"] for i, fab in enumerate(fabricantes_ordem)}
            for it in grupo_itens:
                it["numero_adicao"] = mapa.get(it.get("fabricante_legal"))
            algum_ambiguo_resolvido = True
        else:
            algum_nao_resolvido = True

    if any(it.get("numero_adicao") for it in itens):
        avisos.append(
            "A coluna \"Número da Adição\" é uma INFERÊNCIA: a DUIMP não declara essa informação por "
            "item, apenas o resumo agregado por adição. A associação usa o NCM do item comparado ao "
            "NCM de cada adição" + (
                ", desempatando pelo fabricante/produtor (na ordem em que aparecem) quando o mesmo "
                "NCM aparece em mais de uma adição" if algum_ambiguo_resolvido else ""
            ) + " — confira contra a DI antes de usar para fins fiscais."
        )
    if algum_nao_resolvido:
        avisos.append(
            "Não foi possível inferir com segurança o número da adição de um ou mais itens (NCM sem "
            "correspondência em nenhuma adição, ou ambiguidade que o fabricante/produtor não resolveu) "
            "— a coluna \"Número da Adição\" ficou em branco para esses itens."
        )
    return avisos


def aplicar_rateio_siscomex(cabecalho: dict, itens: list[dict]) -> list[str]:
    """
    Adiciona a cada item (in place) a Taxa Siscomex rateada. Depende de
    `inferir_numero_adicao` já ter sido chamada. Retorna avisos.
    """
    avisos = []
    adicoes = cabecalho.get("adicoes") or []
    taxa_siscomex_total = cabecalho.get("taxa_siscomex")

    for it in itens:
        it["taxa_siscomex_rateada"] = None

    if not adicoes or taxa_siscomex_total is None:
        avisos.append(
            "Não foi possível localizar a Taxa Siscomex do processo — a coluna \"Taxa Siscomex "
            "Rateada\" ficou em branco."
        )
        return avisos

    # Garante que cada adição tenha seu próprio valor de Taxa Siscomex —
    # quando a DI só traz o total do processo (não por adição), rateia pela
    # participação de cada adição na Base de Cálculo PIS/COFINS.
    if any(a.get("taxa_siscomex") is None for a in adicoes):
        total_base = sum(a.get("base_pis_cofins") or 0 for a in adicoes)
        if total_base:
            for a in adicoes:
                if a.get("taxa_siscomex") is None:
                    participacao = (a.get("base_pis_cofins") or 0) / total_base
                    a["taxa_siscomex"] = round(participacao * taxa_siscomex_total, 2)
            avisos.append(
                "A DI não declara a Taxa Siscomex por adição — o valor total do processo foi "
                "rateado entre as adições proporcionalmente à Base de Cálculo PIS/COFINS de cada uma."
            )

    mapa_adicao = {a["numero"]: a for a in adicoes}

    por_adicao: dict = {}
    for it in itens:
        por_adicao.setdefault(it.get("numero_adicao"), []).append(it)

    itens_sem_adicao = []
    for numero_adicao, grupo in por_adicao.items():
        adicao = mapa_adicao.get(numero_adicao)
        if numero_adicao is None or adicao is None or adicao.get("taxa_siscomex") is None:
            itens_sem_adicao.extend(grupo)
            continue
        total_valor_grupo = sum(it.get("valor_total_venda") or 0 for it in grupo)
        if not total_valor_grupo:
            continue
        for it in grupo:
            participacao = (it.get("valor_total_venda") or 0) / total_valor_grupo
            it["taxa_siscomex_rateada"] = round(participacao * adicao["taxa_siscomex"], 2)

    if itens_sem_adicao:
        total_valor_processo = sum(it.get("valor_total_venda") or 0 for it in itens)
        if total_valor_processo:
            for it in itens_sem_adicao:
                participacao = (it.get("valor_total_venda") or 0) / total_valor_processo
                it["taxa_siscomex_rateada"] = round(participacao * taxa_siscomex_total, 2)
        avisos.append(
            "Não foi possível identificar a adição de um ou mais itens — a Taxa Siscomex desses "
            "itens foi rateada pelo valor comercial sobre o total do processo, não pela adição "
            "específica a que pertencem."
        )

    return avisos


_RE_PRAZO = re.compile(r"(\d+)\s*(mes|mês|meses|ano|anos)", re.IGNORECASE)


def _parse_data_br(texto):
    if not texto:
        return None
    try:
        return pd.to_datetime(texto, format="%d/%m/%Y")
    except (ValueError, TypeError):
        return None


def calcular_data_vencimento(itens: list[dict]) -> list[str]:
    """
    Adiciona a cada item (in place) a Data de Vencimento, calculada a partir
    da Data de Fabricação + Prazo de Validade. Não é um campo da DUIMP — é
    uma data derivada; quando o prazo é "INDETERMINADA/INDETERMINADO", não
    há vencimento a calcular (fica em branco, sem gerar aviso). Retorna
    avisos apenas quando o prazo é determinado mas não foi possível
    calcular (formato não reconhecido, ou falta a data de fabricação).
    """
    avisos = []
    algum_nao_calculavel = False

    for it in itens:
        it["data_vencimento"] = None
        prazo = (it.get("prazo_validade") or "").strip()
        if not prazo or "indetermin" in prazo.lower():
            continue

        m = _RE_PRAZO.search(prazo)
        data_fab = _parse_data_br(it.get("data_fabricacao"))
        if not m or data_fab is None:
            algum_nao_calculavel = True
            continue

        qtd = int(m.group(1))
        unidade = m.group(2).lower()
        offset = pd.DateOffset(years=qtd) if unidade.startswith("ano") else pd.DateOffset(months=qtd)
        it["data_vencimento"] = (data_fab + offset).strftime("%d/%m/%Y")

    if algum_nao_calculavel:
        avisos.append(
            "Não foi possível calcular a Data de Vencimento de um ou mais itens (prazo de validade "
            "com formato não reconhecido, ou sem data de fabricação) — confira manualmente esses itens."
        )
    return avisos
