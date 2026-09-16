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


def _valida_chave(digitos: str) -> bool:
    return len(digitos) == 44 and digitos[20:22] == _MOD_CTE


def _extrai_chave_acesso(texto: str) -> str | None:
    """Localiza a chave de acesso do CT-e (44 dígitos), tentando os
    formatos de impressão já observados em DACTEs reais, e confirmando
    pelo dígito do modelo (57) na posição correta dentro da chave —
    evita confundir com a chave de uma NF-e referenciada (modelo 55)."""
    # Formato "oficial": 11 grupos de 4 dígitos separados por espaço.
    for m in re.finditer(r"(?:\d{4}[ .]){10}\d{4}", texto):
        digitos = re.sub(r"\D", "", m.group(0))
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
    m = re.search(r"VALOR A RECEBER\s*\n\s*([\d.,]+)", texto)
    return _to_float(m.group(1)) if m else None


def _extrai_aliquota_icms(texto: str) -> float | None:
    """A linha de tributação do ICMS começa com um código de 2 dígitos
    (ex.: "00 - Tributação normal") seguido de Base de Cálculo, Alíquota,
    Valor do ICMS e, opcionalmente, % de redução — nessa ordem fixa."""
    m = re.search(
        r"^\d{2}\s*-\s*.*?\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)(?:\s+([\d.,]+))?\s*$",
        texto, re.MULTILINE,
    )
    return _to_float(m.group(2)) if m else None


def extrair(conteudo_pdf: bytes, nome_arquivo: str) -> dict:
    """Lê um DACTE em PDF e retorna os campos extraídos + avisos para os
    campos que não foram encontrados."""
    with pdfplumber.open(__import__("io").BytesIO(conteudo_pdf)) as pdf:
        texto = "\n".join(p.extract_text() or "" for p in pdf.pages)

    numero_cte, data_emissao = _extrai_numero_e_data(texto)
    chave_acesso = _extrai_chave_acesso(texto)
    valor_a_receber = _extrai_valor_a_receber(texto)
    aliquota_icms = _extrai_aliquota_icms(texto)

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
