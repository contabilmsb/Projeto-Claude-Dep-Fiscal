"""
Leitura do DACTE (Documento Auxiliar do Conhecimento de Transporte
Eletrônico) em PDF — extrai, por documento, o número do CT-e, a data de
emissão, a chave de acesso (sempre só os 44 dígitos, sem espaços/pontos/
barras/hífens), o valor a receber (frete) e a alíquota do ICMS.

O layout do DACTE varia bastante entre transportadoras (cada uma usa seu
próprio software de emissão), mas alguns rótulos e convenções são
praticamente universais por seguirem o leiaute nacional do CT-e:
  - A tabela "MODELO SÉRIE NÚMERO ... DATA E HORA DE EMISSÃO" no topo do
    documento, com uma linha de rótulos seguida de uma linha de valores.
  - A chave de acesso impressa de forma legível — o mais comum é em 11
    grupos de 4 dígitos separados por espaço (padrão oficial do leiaute),
    mas pelo menos um software observado usa uma máscara diferente
    (CNPJ mascarado + separadores por campo). Como o dígito do modelo
    (57 para CT-e) está numa posição fixa dentro da chave, ele é usado
    para confirmar que o candidato encontrado é mesmo a chave do CT-e
    (e não, por exemplo, a chave de uma NF-e referenciada nos documentos
    originários, que tem modelo 55).
  - A seção "VALOR A RECEBER" com o valor do frete na linha seguinte.
  - A linha de tributação do ICMS (começa com um código de dois dígitos
    seguido de " - " e a descrição), com Base de Cálculo, Alíquota,
    Valor do ICMS e, opcionalmente, % de redução da BC, nessa ordem.
"""

import io
import re

import pdfplumber

_MOD_CTE = "57"


def _to_float(valor: str | None) -> float | None:
    if not valor:
        return None
    try:
        return float(valor.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _extrai_numero_e_data(texto: str) -> tuple[str | None, str | None]:
    """Lê a tabela "MODELO SÉRIE NÚMERO ... DATA E HORA DE EMISSÃO",
    presente em (praticamente) todo leiaute de DACTE — a linha de rótulos
    é seguida pela linha de valores com a mesma ordem de colunas.

    A linha de valores às vezes vem com texto de outra coluna colado na
    frente (leiaute em duas colunas, ex.: parte do endereço do emitente),
    então a busca usa como âncora o "57" do campo Modelo (fixo para
    CT-e), não a posição do primeiro token da linha.
    """
    m = re.search(r"MODELO\s+S[ÉE]RIE\s+N[ÚU]MERO.*\n(.+)", texto)
    if not m:
        return None, None
    linha_valor = m.group(1)
    mv = re.search(
        rf"\b{_MOD_CTE}\s+\S+\s+(\S+)\s+\d+/\d+\s+(\d{{2}}/\d{{2}}/\d{{4}}\s+\d{{2}}:\d{{2}}:\d{{2}})",
        linha_valor,
    )
    if not mv:
        return None, None
    numero = re.sub(r"\D", "", mv.group(1)).lstrip("0") or "0"
    data_emissao = mv.group(2).split()[0]  # descarta a hora, mantém só dd/mm/aaaa
    return numero, data_emissao


_RE_LAYOUT_SSW = re.compile(r"S[ÉE]RIE\s+N[ÚU]MERO\s+MODAL\s+MODELO")


def _eh_layout_ssw(texto: str) -> bool:
    """Leiaute do sistema SSW (ex.: Camilo dos Santos): o cabeçalho traz
    "SÉRIE NÚMERO MODAL MODELO Nº PROTOCOLO" e a data fica na linha de
    "AUTORIZAÇÃO FL"."""
    return bool(_RE_LAYOUT_SSW.search(texto))


def _data_com_ano_4_digitos(data: str) -> str:
    dia, mes, ano = data.split("/")
    return f"{dia}/{mes}/{ano if len(ano) == 4 else '20' + ano}"


def _extrai_numero_e_data_ssw(texto: str) -> tuple[str | None, str | None]:
    """Número: "<série> <9 dígitos> <modal> 57 <protocolo>" (âncora no 57 do
    modelo). Data: linha logo abaixo de "AUTORIZAÇÃO FL" (dd/mm/aa hh:mm 1/1)."""
    numero = data = None
    m = re.search(rf"\b\d{{1,3}}\s+(\d{{9}})\s+[^\W\d_]+\s+{_MOD_CTE}\s+\d{{10,}}", texto)
    if m:
        numero = m.group(1).lstrip("0") or "0"
    d = re.search(
        r"AUTORIZA[ÇC][ÃA]O\s+FL\s*\n[^\n]*?(\d{2}/\d{2}/\d{2,4})\s+\d{2}:\d{2}\s+\d+/\d+", texto
    )
    if d:
        data = _data_com_ano_4_digitos(d.group(1))
    return numero, data


def _extrai_aliquota_icms_ssw(texto: str) -> float | None:
    """"ALIQ DIFAL/ICMS(%) <difal> <icms>" — a alíquota do ICMS é o segundo valor."""
    m = re.search(r"ALIQ\s+DIFAL/ICMS\(%\)\s+([\d.,]+)\s+([\d.,]+)", texto)
    return _to_float(m.group(2)) if m else None


def _valida_chave(digitos: str) -> bool:
    return len(digitos) == 44 and digitos[20:22] == _MOD_CTE


def _extrai_chave_acesso(texto: str) -> str | None:
    """Localiza a chave de acesso do CT-e (44 dígitos), tentando os
    formatos de impressão já observados em DACTEs reais, e confirmando
    pelo dígito do modelo (57) na posição correta dentro da chave —
    evita confundir com a chave de uma NF-e referenciada (modelo 55)."""
    # Formato "oficial": 11 grupos de 4 dígitos separados por espaço.
    # Lookahead (busca sobreposta) + limite de dígitos: números vizinhos na
    # mesma linha (ex.: final da inscrição estadual colado antes da chave)
    # não podem "consumir" o início da chave real.
    for m in re.finditer(r"(?<!\d)(?=((?:\d{4}[ .]){10}\d{4})(?!\d))", texto):
        digitos = re.sub(r"\D", "", m.group(1))
        if _valida_chave(digitos):
            return digitos

    # Formato "mascarado" observado em ao menos um software de emissão:
    # UF.AAMM.CNPJ-mascarado-MOD-SERIE-NUMERO(pontuado)-TPEMIS.CNF-CDV.
    padrao_mascarado = (
        r"\d{2}\.\d{4}\.\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}-\d{2}-\d{3}"
        r"-\d{3}\.\d{3}\.\d{3}-\d{3}\.\d{3}\.\d{3}-\d{1}"
    )
    m = re.search(padrao_mascarado, texto)
    if m:
        digitos = re.sub(r"\D", "", m.group(0))
        if _valida_chave(digitos):
            return digitos

    return None


def _extrai_valor_a_receber(texto: str) -> float | None:
    m = re.search(r"VALOR A RECEBER(?:\s*\(R\$\))?\s+([\d.,]+)", texto)
    return _to_float(m.group(1)) if m else None


def _extrai_aliquota_icms(texto: str) -> float | None:
    """A linha de tributação do ICMS começa com um código de 2 dígitos
    (ex.: "00 - Tributação normal") seguido de Base de Cálculo, Alíquota,
    Valor do ICMS e, opcionalmente, % de redução — nessa ordem fixa."""
    # Só olha a partir do bloco do imposto, para não confundir com outras
    # linhas do documento que também comecem com "NN - ".
    i = texto.find("INFORMAÇÕES RELATIVAS AO IMPOSTO")
    bloco = texto[i:] if i >= 0 else texto
    m = re.search(
        r"^\d{2}\s*-\s*.*?\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)(?:\s+([\d.,]+))?\s*$",
        bloco, re.MULTILINE,
    )
    if m:
        return _to_float(m.group(2))
    # Situações sem ICMS destacado (40 isenção, 41 não tributada, 51
    # diferimento) vêm sem coluna de alíquota — o ICMS é zero.
    if re.search(r"^(?:40|41|51)\s*-", bloco, re.MULTILINE):
        return 0.0
    return None


def _eh_pagina_dacte(texto_pagina: str) -> bool:
    return "VALOR A RECEBER" in texto_pagina and (
        bool(re.search(r"MODELO\s+S[ÉE]RIE\s+N[ÚU]MERO", texto_pagina)) or _eh_layout_ssw(texto_pagina)
    )


def _eh_pagina_fatura(texto_pagina: str) -> bool:
    return "Qtd. Remessas" in texto_pagina or "Dados do sacado" in texto_pagina


def _brl(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _confere_fatura(texto_fatura: str, linhas: list[dict], nome_arquivo: str) -> list[str]:
    """Quando o PDF traz a fatura da transportadora junto com os DACTEs, confere
    a quantidade de remessas e o valor total da fatura com o que foi extraído."""
    m = re.search(
        r"Qtd\. Remessas\s+(\d+)\s+Totais\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)", texto_fatura
    )
    if not m:
        return []
    qtd_fatura, total_fatura = int(m.group(1)), _to_float(m.group(4))
    total_extraido = round(sum(l.get("valor_a_receber") or 0.0 for l in linhas), 2)
    avisos = []
    if qtd_fatura != len(linhas):
        avisos.append(
            f"{nome_arquivo}: a fatura informa {qtd_fatura} remessa(s), mas foram encontrados "
            f"{len(linhas)} DACTE(s) no arquivo — confira se alguma página está faltando."
        )
    if total_fatura is not None and abs(total_fatura - total_extraido) > 0.01:
        avisos.append(
            f"{nome_arquivo}: o total da fatura (R$ {_brl(total_fatura)}) não fecha com a soma dos "
            f"valores a receber extraídos (R$ {_brl(total_extraido)})."
        )
    return avisos


def extrair_todos(conteudo_pdf: bytes, nome_arquivo: str) -> tuple[list[dict], list[str]]:
    """
    Lê um PDF com um ou vários DACTEs e retorna (lista de DACTEs extraídos,
    avisos gerais do arquivo).

    Um PDF pode trazer vários DACTEs em sequência (um por página, ou mais) e,
    antes deles, a fatura da transportadora. Cada página que parece o início
    de um DACTE abre um novo documento; páginas seguintes sem esse início
    (continuação) são juntadas ao documento anterior; páginas de fatura são
    ignoradas na extração e usadas só para conferir quantidade e total.
    """
    paginas: list[str] = []
    fontes: list[str] = []  # texto separado por fonte (só nas páginas do leiaute SSW)
    with pdfplumber.open(io.BytesIO(conteudo_pdf)) as pdf:
        for p in pdf.pages:
            texto = p.extract_text() or ""
            paginas.append(texto)
            # No leiaute SSW a chave de acesso (fonte 7pt) é impressa sobre uma
            # frase em outra fonte (5pt), e a extração comum intercala os
            # caracteres das duas; separar por fonte devolve a chave inteira.
            fontes.append(p.extract_text(extra_attrs=["fontname", "size"]) or "" if _eh_layout_ssw(texto) else "")

    grupos: list[dict] = []  # {"pagina": n, "textos": [..], "fontes": [..]}
    textos_fatura: list[str] = []
    for n, texto in enumerate(paginas, start=1):
        if _eh_pagina_dacte(texto):
            grupos.append({"pagina": n, "textos": [texto], "fontes": [fontes[n - 1]]})
        elif _eh_pagina_fatura(texto):
            textos_fatura.append(texto)
        elif grupos:
            grupos[-1]["textos"].append(texto)
            grupos[-1]["fontes"].append(fontes[n - 1])

    if not grupos:  # nenhuma página reconhecida: tenta o arquivo todo como um documento
        grupos = [{"pagina": 1, "textos": paginas, "fontes": fontes}]

    varios = len(grupos) > 1
    linhas = [
        _extrai_documento(
            "\n".join(g["textos"]),
            f"{nome_arquivo} (p. {g['pagina']})" if varios else nome_arquivo,
            "\n".join(g["fontes"]),
        )
        for g in grupos
    ]
    avisos_gerais = _confere_fatura("\n".join(textos_fatura), linhas, nome_arquivo) if textos_fatura else []
    return linhas, avisos_gerais


def _extrai_documento(texto: str, nome_arquivo: str, texto_fontes: str = "") -> dict:
    """Extrai os campos de um único DACTE a partir do texto dele."""
    if _eh_layout_ssw(texto):
        numero_cte, data_emissao = _extrai_numero_e_data_ssw(texto)
        chave_acesso = _extrai_chave_acesso(texto_fontes) or _extrai_chave_acesso(texto)
        aliquota_icms = _extrai_aliquota_icms_ssw(texto)
    else:
        numero_cte, data_emissao = _extrai_numero_e_data(texto)
        chave_acesso = _extrai_chave_acesso(texto)
        aliquota_icms = _extrai_aliquota_icms(texto)
    valor_a_receber = _extrai_valor_a_receber(texto)

    avisos = []
    if not numero_cte:
        avisos.append(f"{nome_arquivo}: não foi possível identificar o número do CT-e.")
    if not data_emissao:
        avisos.append(f"{nome_arquivo}: não foi possível identificar a data de emissão.")
    if not chave_acesso:
        avisos.append(f"{nome_arquivo}: não foi possível identificar a chave de acesso.")
    if valor_a_receber is None:
        avisos.append(f"{nome_arquivo}: não foi possível identificar o valor a receber.")
    if aliquota_icms is None:
        avisos.append(f"{nome_arquivo}: não foi possível identificar a alíquota de ICMS.")

    return {
        "arquivo": nome_arquivo,
        "numero_cte": numero_cte,
        "data_emissao": data_emissao,
        "chave_acesso": chave_acesso,
        "valor_a_receber": valor_a_receber,
        "aliquota_icms": aliquota_icms,
        "avisos": avisos,
    }
