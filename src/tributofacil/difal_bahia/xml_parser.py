"""
Leitura de arquivos XML de NF-e para apuração do DIFAL de compras
destinadas ao Estado da Bahia (uso, consumo ou ativo imobilizado).

Base legal: Lei nº 7.014/1996, art. 4º XV e art. 17 XI e §6º.

Para cada item (<det>) da NF-e, extrai o valor da operação (vProd +
acessórios) e a alíquota interestadual EFETIVA (ICMS destacado / valor da
operação):
  - Quando o item tem ICMS próprio destacado (vICMS, em ICMS00, ICMS10,
    ICMS20 etc.): a alíquota efetiva é calculada sobre o valor total do
    item, não sobre uma eventual base reduzida — isso evita duplicar uma
    redução de base que já está embutida no vICMS.
  - Se o item é do Simples Nacional sem destaque de ICMS próprio
    (ICMSSN101, ICMSSN102, ICMSSN103, ICMSSN300, ICMSSN400): assume
    alíquota interestadual de 0%.
  - Sinaliza substituição tributária quando há vBCST/pICMSST/vICMSST no
    item, para aplicar a fórmula de DIFAL-ST em vez da fórmula normal.
  - Sinaliza itens com redução de base do ICMS amparada pelo Convênio
    ICMS 52/91 (identificado via menção ao convênio nas Informações
    Complementares da nota, combinada com a presença de pRedBC no item):
    a Bahia reconhece esse benefício também na operação equivalente
    interna (Art. 266 do RICMS-BA), então o DIFAL desses itens deve usar
    a alíquota interna reduzida de 5,60%, não os 20,5% padrão.
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

NS = {"nfe": "http://www.portalfiscal.inf.br/nfe"}

_RE_CONVENIO_5291 = re.compile(r"conv[eê]nio\s*(?:icms)?\s*n?[o°º]?\.?\s*52[\s/.\-]*91", re.IGNORECASE)


def _t(el, path: str, default: str | None = None) -> str | None:
    if el is None:
        return default
    node = el.find(path, NS)
    return node.text if node is not None and node.text is not None else default


def _f(el, path: str, default: float = 0.0) -> float:
    v = _t(el, path)
    if v is None:
        return default
    try:
        return float(v)
    except ValueError:
        return default


@dataclass
class ItemDifal:
    arquivo: str
    chave_nfe: str
    numero_nf: str
    data_emissao: str
    cnpj_emitente: str
    nome_emitente: str
    uf_origem: str
    uf_destino: str
    regime_emitente: str          # "Normal" ou "Simples Nacional"
    cfop: str
    n_item: str
    descricao_produto: str
    valor_operacao: float          # vProd + acessórios (frete/seguro/outras despesas - desconto)
    aliquota_interestadual: float  # efetiva: vICMS destacado / valor_operacao (decimal, ex.: 0.07)
    icms_destacado: bool           # False quando não há ICMS próprio destacado no XML (Simples Nacional)
    substituicao_tributaria: bool
    reducao_base_convenio_5291: bool  # base de ICMS reduzida ao amparo do Convênio ICMS 52/91
    percentual_reducao_bc: float | None  # pRedBC do item, quando houver (informativo)
    ind_final: str                 # indFinal — 1 = consumidor final


def _regime(crt: str | None) -> str:
    return "Simples Nacional" if crt == "1" else "Normal"


def _nota_menciona_convenio_5291(inf_nfe) -> bool:
    inf_adic = inf_nfe.find("nfe:infAdic", NS)
    texto = (_t(inf_adic, "nfe:infCpl", "") or "") + " " + (_t(inf_adic, "nfe:infAdFisco", "") or "")
    return bool(_RE_CONVENIO_5291.search(texto))


def _extrai_item(det, ide, emit, dest, arquivo: str, chave: str, nota_convenio_5291: bool) -> ItemDifal:
    prod = det.find("nfe:prod", NS)
    imposto = det.find("nfe:imposto", NS)
    icms = imposto.find("nfe:ICMS", NS) if imposto is not None else None
    icms_node = next(iter(icms), None) if icms is not None else None

    v_icms = None
    st = False
    p_red_bc = None
    if icms_node is not None:
        v_icms_txt = _t(icms_node, "nfe:vICMS")
        if v_icms_txt is not None:
            v_icms = float(v_icms_txt)
        p_red_bc_txt = _t(icms_node, "nfe:pRedBC")
        if p_red_bc_txt is not None:
            p_red_bc = float(p_red_bc_txt)
        if _t(icms_node, "nfe:vBCST") or _t(icms_node, "nfe:pICMSST") or _t(icms_node, "nfe:vICMSST"):
            st = True

    v_prod = _f(prod, "nfe:vProd")
    v_frete = _f(prod, "nfe:vFrete")
    v_seg = _f(prod, "nfe:vSeg")
    v_outro = _f(prod, "nfe:vOutro")
    v_desc = _f(prod, "nfe:vDesc")
    valor_operacao = v_prod + v_frete + v_seg + v_outro - v_desc

    icms_destacado = v_icms is not None
    # Alíquota EFETIVA sobre o valor total do item — não sobre uma eventual
    # base reduzida (pRedBC), para não aplicar a redução em dobro.
    aliquota = (v_icms / valor_operacao) if (icms_destacado and valor_operacao > 0) else 0.0

    convenio_5291 = nota_convenio_5291 and p_red_bc is not None

    crt = _t(emit, "nfe:CRT")

    return ItemDifal(
        arquivo=arquivo,
        chave_nfe=chave,
        numero_nf=_t(ide, "nfe:nNF", "") or "",
        data_emissao=(_t(ide, "nfe:dhEmi") or _t(ide, "nfe:dEmi") or ""),
        cnpj_emitente=_t(emit, "nfe:CNPJ", "") or "",
        nome_emitente=_t(emit, "nfe:xNome", "") or "",
        uf_origem=_t(emit, "nfe:enderEmit/nfe:UF", "") or "",
        uf_destino=_t(dest, "nfe:enderDest/nfe:UF", "") or "",
        regime_emitente=_regime(crt),
        cfop=_t(prod, "nfe:CFOP", "") or "",
        n_item=det.get("nItem", ""),
        descricao_produto=_t(prod, "nfe:xProd", "") or "",
        valor_operacao=valor_operacao,
        aliquota_interestadual=aliquota,
        icms_destacado=icms_destacado,
        substituicao_tributaria=st,
        reducao_base_convenio_5291=convenio_5291,
        percentual_reducao_bc=p_red_bc,
        ind_final=_t(ide, "nfe:indFinal", "") or "",
    )


def parse_nfe_xml(path: Path, arquivo_nome: str | None = None) -> list[ItemDifal]:
    """Extrai um ItemDifal por item (<det>) do XML de NF-e informado."""
    tree = ET.parse(path)
    root = tree.getroot()

    inf_nfe = root.find(".//nfe:infNFe", NS)
    if inf_nfe is None:
        raise ValueError(f"Arquivo {path.name} não parece ser um XML de NF-e válido (infNFe não encontrado).")

    chave = (inf_nfe.get("Id") or "").replace("NFe", "")
    ide = inf_nfe.find("nfe:ide", NS)
    emit = inf_nfe.find("nfe:emit", NS)
    dest = inf_nfe.find("nfe:dest", NS)
    nota_convenio_5291 = _nota_menciona_convenio_5291(inf_nfe)

    itens = []
    for det in inf_nfe.findall("nfe:det", NS):
        itens.append(_extrai_item(det, ide, emit, dest, arquivo_nome or path.name, chave, nota_convenio_5291))
    return itens
