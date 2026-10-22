"""
Leitura de XML de NF-e (modelo 55/65) — extrai, por nota, os dados de
cabeçalho usados na conferência fiscal: data de emissão, CNPJ/CPF do
emitente e do destinatário, CFOP(s), valor total da nota, base de cálculo e
valor do ICMS (totais da nota, grupo <ICMSTot>).

O CFOP é informado por item; quando a nota tem itens com CFOPs diferentes,
todos aparecem (sem repetição, na ordem em que surgem), separados por " / ".
"""

import re
import xml.etree.ElementTree as ET

NS = {"nfe": "http://www.portalfiscal.inf.br/nfe"}


def _t(el, path: str) -> str | None:
    if el is None:
        return None
    node = el.find(path, NS)
    return node.text.strip() if node is not None and node.text else None


def _f(el, path: str) -> float | None:
    v = _t(el, path)
    try:
        return float(v) if v is not None else None
    except ValueError:
        return None


def _documento(parte) -> str | None:
    """CNPJ (ou CPF, quando a parte é pessoa física) só com dígitos, como no XML."""
    return _t(parte, "nfe:CNPJ") or _t(parte, "nfe:CPF")


def _data_br(data_hora: str | None) -> str | None:
    """dhEmi (aaaa-mm-ddThh:mm:ss-03:00) ou dEmi (aaaa-mm-dd) -> dd/mm/aaaa."""
    if not data_hora or len(data_hora) < 10:
        return None
    ano, mes, dia = data_hora[:10].split("-")
    return f"{dia}/{mes}/{ano}"


_RE_TEXTO_LIVRE = re.compile(r"(<(infCpl|infAdFisco)>)(.*?)(</\2>)", re.DOTALL)
_RE_AMP_SOLTO = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)")


def _escapa_texto_livre(conteudo: bytes) -> bytes:
    """Alguns emitentes digitam "<" ou "&" soltos nas informações complementares
    (ex.: "<No. do Pedido>"), o que torna o XML inválido mesmo com os dados da
    nota íntegros. Escapa só esses dois campos de texto livre."""
    texto = conteudo.decode("utf-8", errors="replace")

    def ajusta(m):
        miolo = _RE_AMP_SOLTO.sub("&amp;", m.group(3)).replace("<", "&lt;")
        return f"{m.group(1)}{miolo}{m.group(4)}"

    return _RE_TEXTO_LIVRE.sub(ajusta, texto).encode("utf-8")


def extrair(conteudo_xml: bytes, nome_arquivo: str) -> dict:
    try:
        root = ET.fromstring(conteudo_xml)
    except ET.ParseError:
        try:
            root = ET.fromstring(_escapa_texto_livre(conteudo_xml))
        except ET.ParseError as e:
            raise ValueError(f"XML inválido ({e})") from e

    inf = root.find(".//nfe:infNFe", NS)
    if inf is None:
        raise ValueError("não parece ser um XML de NF-e (grupo infNFe não encontrado)")

    ide = inf.find("nfe:ide", NS)
    tot = inf.find("nfe:total/nfe:ICMSTot", NS)

    cfops: list[str] = []
    for det in inf.findall("nfe:det", NS):
        cfop = _t(det, "nfe:prod/nfe:CFOP")
        if cfop and cfop not in cfops:
            cfops.append(cfop)

    r = {
        "arquivo": nome_arquivo,
        "numero_nf": _t(ide, "nfe:nNF"),
        "data_emissao": _data_br(_t(ide, "nfe:dhEmi") or _t(ide, "nfe:dEmi")),
        "cnpj_emitente": _documento(inf.find("nfe:emit", NS)),
        "cnpj_destinatario": _documento(inf.find("nfe:dest", NS)),
        "cfop": " / ".join(cfops) or None,
        "valor_total_nota": _f(tot, "nfe:vNF"),
        "base_calculo_icms": _f(tot, "nfe:vBC"),
        "valor_icms": _f(tot, "nfe:vICMS"),
    }

    avisos = []
    nomes = {
        "data_emissao": "data de emissão", "cnpj_emitente": "CNPJ do emitente", "cfop": "CFOP",
        "valor_total_nota": "valor total da nota", "base_calculo_icms": "base de cálculo do ICMS",
        "valor_icms": "valor do ICMS",
    }
    for chave, nome in nomes.items():
        if r[chave] is None:
            avisos.append(f"{nome_arquivo}: não foi possível identificar {nome}.")
    r["avisos"] = avisos
    return r
