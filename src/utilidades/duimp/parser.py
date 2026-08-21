"""
Leitura do Extrato da DUIMP (PDF) — extrai os dados do processo (cabeçalho)
e de cada item/mercadoria importada.

A DUIMP não traz o peso bruto nem os tributos (II/IPI/PIS/COFINS) detalhados
por item — só o total do processo (peso bruto) e o total por "adição" do
Siscomex (tributos). O rateio desses valores por item é feito em calculos.py.

O texto do PDF é extraído com pdfplumber. Os campos são localizados por rótulo
exato (o texto do rótulo, ex. "Número do Lote"), não por posição — a ordem dos
campos varia de um item para outro no mesmo extrato.
"""

import io
import re

import pdfplumber

HEADER_RE = re.compile(r"^Extrato da DUIMP .*\(hor[aá]rio de Bras[ií]lia\).*$", re.MULTILINE)
FOOTER_RE = re.compile(r"^\d+\s*/\s*\d+$", re.MULTILINE)
ITEM_SPLIT_RE = re.compile(r"Extrato da Duimp \S+ / Vers[ãa]o \d+ : Item (\d+)")

# Rótulos conhecidos do extrato — usados para saber onde um valor multi-linha
# termina (o próximo rótulo encontrado interrompe a captura).
KNOWN_LABELS = {
    "NCM:", "Part number", "Fabricante Legal", "Número de regularização no SNVS",
    "Apresentação comercial - Anvisa", "Descrição complementar da mercadoria:",
    "Número do Lote", "Data de fabricação do bem/produto Anvisa",
    "Código de Class. Tributária (cClassTrib)", "CNPJ / CPF Destino final",
    "Finalidade da importação - Anvisa", "Dispositivo médico recondicionado",
    "Critério de priorização - Anvisa", "Valor total na condição de venda:",
    "Detalhamento do Produto:", "Número de série", "CNPJ destinatário ensaio de proficiência",
    "CNPJ provedor do ensaio de proficiência", "Prazo de validade", "Condição de armazenamento",
    "Estágio de fabricação", "Dispositivo médico ou componente estéril", "Método de esterilização",
    "Contém derivado de animal ruminante", "Categoria de produto - Catálogo Anvisa", "Endereço:",
    "Tributos", "Tributação", "Tributo Regime de Tributação Fundamento", "Atributos Adicionais",
    "Tipo de Mercadoria Importada:", "Tipo de Pessoa Jurídica:",
    "Dados do Exportador Estrangeiro (Fornecedor)", "Dados da Mercadoria",
    "Informações Complementares da Mercadoria", "Mercadoria", "Caracterização da Importação",
    "Indicação de importação para terceiros:", "Dados do Produto",
    "Código do produto: Versão:", "Fabricante / Produtor",
    "País de origem: Número de Identificação (CPF/CNPJ/TIN):",
    "Código do Fabricante/Produtor: Versão:",
    "Relação entre exportador e fabricante/produtor: Vinculação entre comprador e vendedor:",
    "País de aquisição: Número de identificação (TIN):",
    "Código do Exportador Estrangeiro: Versão:",
    "Aplicação: Condição da mercadoria:",
    "Unidade estatística: Quantidade na unidade estatística:",
    "Peso líquido (kg): Quantidade na unidade comercializada:",
    "Moeda negociada: Valor unitário na condição de venda:",
}


def _clean_page_text(text: str) -> str:
    text = HEADER_RE.sub("", text)
    linhas = [l for l in text.split("\n") if not FOOTER_RE.match(l.strip())]
    return "\n".join(linhas)


def _find_value(text: str, label: str, multiline: bool = False):
    linhas = [l.rstrip() for l in text.split("\n")]
    for i, l in enumerate(linhas):
        if l.strip() != label:
            continue
        if not multiline:
            return linhas[i + 1].strip() if i + 1 < len(linhas) else None
        partes = []
        j = i + 1
        while j < len(linhas):
            prox = linhas[j].strip()
            if not prox:
                j += 1
                continue
            if prox in KNOWN_LABELS:
                break
            partes.append(prox)
            j += 1
            if len(partes) >= 4:
                break
        return " ".join(partes) if partes else None
    return None


def _to_float(valor):
    if valor is None or valor == "":
        return None
    try:
        return float(valor.replace(".", "").replace(",", "."))
    except (ValueError, AttributeError):
        return None


def _parse_item(numero_item: int, texto: str) -> dict:
    d = {"item": numero_item}

    d["ncm"] = _find_value(texto, "NCM:")
    d["part_number"] = _find_value(texto, "Part number")
    d["fabricante_legal"] = _find_value(texto, "Fabricante Legal")
    d["numero_snvs"] = _find_value(texto, "Número de regularização no SNVS")
    d["descricao_complementar"] = _find_value(texto, "Descrição complementar da mercadoria:", multiline=True)
    d["numero_lote"] = _find_value(texto, "Número do Lote")
    d["data_fabricacao"] = _find_value(texto, "Data de fabricação do bem/produto Anvisa")
    d["cclasstrib"] = _find_value(texto, "Código de Class. Tributária (cClassTrib)", multiline=True)
    d["cnpj_destino_final"] = _find_value(texto, "CNPJ / CPF Destino final")
    d["finalidade_importacao"] = _find_value(texto, "Finalidade da importação - Anvisa")
    d["dispositivo_recondicionado"] = _find_value(texto, "Dispositivo médico recondicionado")

    v = _find_value(texto, "País de origem: Número de Identificação (CPF/CNPJ/TIN):")
    if v:
        m = re.match(r"^(.*? - [A-Z]{2})\s+(\S+)$", v)
        d["pais_origem"] = m.group(1) if m else v

    v = _find_value(texto, "País de aquisição: Número de identificação (TIN):")
    if v:
        m = re.match(r"^(.*? - [A-Z]{2})", v)
        d["pais_aquisicao"] = m.group(1).strip() if m else v

    v = _find_value(texto, "Código do Exportador Estrangeiro: Versão:")
    if v:
        m = re.match(r"^(\S+) - (.+?)\s+\d+(?:\.\d+)?$", v)
        d["fornecedor"] = m.group(2) if m else v

    v = _find_value(texto, "Peso líquido (kg): Quantidade na unidade comercializada:")
    if v:
        m = re.match(r"^([\d.,]+)\s+([\d.,]+)$", v)
        if m:
            d["peso_liquido_kg"] = _to_float(m.group(1))
            d["quantidade"] = _to_float(m.group(2))

    v = _find_value(texto, "Moeda negociada: Valor unitário na condição de venda:")
    if v:
        m = re.match(r"^(.+?)\s+([\d.,]+)$", v)
        if m:
            d["moeda_negociada"] = m.group(1)
            d["valor_unitario"] = _to_float(m.group(2))

    d["valor_total_venda"] = _to_float(_find_value(texto, "Valor total na condição de venda:"))

    for trib, chave in [("PIS", "pis"), ("Cofins", "cofins"), ("II", "ii"), ("IPI", "ipi")]:
        m = re.search(
            rf"^{trib}\s+(REDUCAO|RECOLHIMENTO INTEGRAL|ISENCAO|SUSPENSAO|N[AÃ]O INCIDENCIA)\s+"
            rf"(.*?)(?=^(?:PIS|Cofins|II|IPI)\s|\Z)",
            texto, re.MULTILINE | re.DOTALL,
        )
        if m:
            fundamento = " ".join(m.group(2).split())
            fundamento = re.split(r"Atributos Adicionais|Extrato da Duimp", fundamento)[0].strip()
            d[f"{chave}_regime"] = m.group(1)
            d[f"{chave}_fundamento"] = fundamento[:200]

    return d


def _parse_cabecalho(texto: str) -> dict:
    h = {}

    m = re.search(r"Extrato da Duimp (\S+) / Vers[ãa]o (\d+)", texto, re.IGNORECASE)
    if m:
        h["duimp_numero"], h["versao"] = m.groups()

    m = re.search(r"CNPJ do importador: Nome do importador:\n([\d./-]+)\s+(.+?)\n(.+?)\n", texto)
    if m:
        h["importador_cnpj"] = m.group(1)
        h["importador_nome"] = f"{m.group(2)} {m.group(3)}".strip()

    campos_simples = [
        ("taxa_dolar", r"TAXA DO D[OÓ]LAR AMERICANO - R\$ ([\d.,]+)"),
        ("taxa_siscomex", r"TAXA UTILIZAÇÃO DO SISCOMEX \(\d+\)\.*:\s*R\$ ([\d.,]+)"),
        ("icms_total", r"VALOR TOTAL DO ICMS \.+:\s*R\$ ([\d.,]+)"),
        ("despesas_aduaneiras", r"DESPESAS ADUANEIRAS\.:\s*R\$ ([\d.,]+)"),
        ("processo_virtua", r"PROCESSO VIRTUA COMEX\.:\s*(.+)"),
        ("processo_biomedical", r"PROCESSO BIOMEDICAL\.:\s*(.+)"),
        ("fatura_comercial", r"FATURA COMERCIAL\.:\s*(.+)"),
        ("data_embarque", r"DATA DE EMBARQUE\.:\s*([\d.]+)"),
        ("data_chegada", r"DATA DE CHEGADA EM \S+\.:\s*([\d.]+)"),
        ("peso_bruto_total_kg", r"Conhecimento\s+\d+\s+([\d.,]+)"),
    ]
    for chave, padrao in campos_simples:
        m = re.search(padrao, texto)
        if m:
            h[chave] = m.group(1).strip()

    for chave, padrao in [
        ("fob", r"FOB\.+:USD ([\d.,]+) - R\$ ([\d.,]+)"),
        ("frete", r"FRETE INTERNACIONAL\.+:USD ([\d.,]+) - R\$ ([\d.,]+)"),
        ("seguro", r"SEGURO \.+:USD ([\d.,]+) - R\$ ([\d.,]+)"),
        ("valor_aduaneiro", r"VALOR ADUANEIRO\.+:USD ([\d.,]+) - R\$ ([\d.,]+)"),
    ]:
        m = re.search(padrao, texto)
        if m:
            h[f"{chave}_usd"], h[f"{chave}_brl"] = m.groups()

    m = re.search(r"EXPORTADOR/FABRICANTE\.:\s*(.+?)(?=\nFATURA COMERCIAL)", texto, re.DOTALL)
    if m:
        h["exportador_fabricante"] = " ".join(m.group(1).split())

    m = re.search(r"[A-Za-z].*?- ([A-Z]{2})\s+([\d]+,[\d]+)\s+Carga", texto)
    if m:
        h["peso_liquido_total_kg"] = m.group(2)

    adicoes = []
    for m in re.finditer(
        r"ADIÇÃO (\d+) - NCM: (\S+)\n"
        r"0086-II \([\d.,]+%\).*?:\s*R\$ ([\d.,]+)\n"
        r"1038-IPI\([\d.,]+%\)\s*.*?:\s*R\$ ([\d.,]+)\n"
        r"BASE DE CALCULO \(PIS/COFINS\)\.*:\s*R\$ ([\d.,]+)\n"
        r"5602-PIS/PASEP \([\d.,]+%\).*?:\s*R\$ ([\d.,]+)\n"
        r"5629-COFINS\([\d.,]+%\).*?:\s*R\$ ([\d.,]+)",
        texto,
    ):
        adicoes.append({
            "numero": m.group(1), "ncm": m.group(2),
            "ii_valor": _to_float(m.group(3)), "ipi_valor": _to_float(m.group(4)),
            "base_pis_cofins": _to_float(m.group(5)),
            "pis_valor": _to_float(m.group(6)), "cofins_valor": _to_float(m.group(7)),
        })
    h["adicoes"] = adicoes

    for chave in ["taxa_dolar", "taxa_siscomex", "icms_total", "despesas_aduaneiras",
                  "peso_bruto_total_kg", "peso_liquido_total_kg",
                  "fob_usd", "fob_brl", "frete_usd", "frete_brl",
                  "seguro_usd", "seguro_brl", "valor_aduaneiro_usd", "valor_aduaneiro_brl"]:
        if chave in h:
            h[chave] = _to_float(h[chave])

    return h


def extrair(conteudo_pdf: bytes) -> dict:
    """Lê o PDF do Extrato da DUIMP e retorna {"cabecalho": {...}, "itens": [...]}."""
    with pdfplumber.open(io.BytesIO(conteudo_pdf)) as pdf:
        paginas = [_clean_page_text(p.extract_text() or "") for p in pdf.pages]

    texto_completo = "\n".join(paginas)
    matches = list(ITEM_SPLIT_RE.finditer(texto_completo))
    if not matches:
        raise ValueError(
            "Não foi possível localizar nenhum item na DUIMP — confirme que o arquivo é um "
            "\"Extrato da DUIMP\" em PDF (texto selecionável, não uma digitalização/imagem)."
        )

    texto_cabecalho = texto_completo[: matches[0].start()]
    cabecalho = _parse_cabecalho(texto_cabecalho)

    itens = []
    for i, m in enumerate(matches):
        inicio = m.end()
        fim = matches[i + 1].start() if i + 1 < len(matches) else len(texto_completo)
        itens.append(_parse_item(int(m.group(1)), texto_completo[inicio:fim]))

    return {"cabecalho": cabecalho, "itens": itens}
