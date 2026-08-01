"""
Leitura de arquivos XML de NF-e para apuração do DIFAL de compras
destinadas ao Estado da Bahia (uso, consumo ou ativo imobilizado).

Base legal: Lei nº 7.014/1996, art. 4º XV e art. 17 XI e §6º.

Para cada item (<det>) da NF-e, extrai o valor da operação e a alíquota
interestadual a partir do próprio ICMS destacado no XML:
  - Se o item tem "vBC"/"pICMS" destacados (ICMS00, ICMS10, ICMS20, ...):
    usa esses valores diretamente.
  - Se o item é do Simples Nacional sem destaque de ICMS (ICMSSN101,
    ICMSSN102, ICMSSN103, ICMSSN300, ICMSSN400): assume alíquota
    interestadual de 0% e usa o valor do produto (+ acessórios) como
    valor da operação.
  - Sinaliza substituição tributária quando há vBCST/pICMSST/vICMSST no
    item, para aplicar a fórmula de DIFAL-ST em vez da fórmula normal.
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

NS = {"nfe": "http://www.portalfiscal.inf.br/nfe"}


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
    valor_operacao: float         # base usada no cálculo (vBC destacado, ou vProd + acessórios)
    aliquota_interestadual: float  # decimal (ex.: 0.07)
    icms_destacado: bool           # False quando não há vBC/pICMS no XML (Simples Nacional)
    substituicao_tributaria: bool
    ind_final: str                 # indFinal — 1 = consumidor final


def _regime(crt: str | None) -> str:
    return "Simples Nacional" if crt == "1" else "Normal"


def _extrai_item(det, ide, emit, dest, arquivo: str, chave: str) -> ItemDifal:
    prod = det.find("nfe:prod", NS)
    imposto = det.find("nfe:imposto", NS)
    icms = imposto.find("nfe:ICMS", NS) if imposto is not None else None
    icms_node = next(iter(icms), None) if icms is not None else None

    v_bc = None
    p_icms = None
    st = False
    if icms_node is not None:
        v_bc_txt = _t(icms_node, "nfe:vBC")
        p_icms_txt = _t(icms_node, "nfe:pICMS")
        if v_bc_txt is not None and p_icms_txt is not None:
            v_bc = float(v_bc_txt)
            p_icms = float(p_icms_txt) / 100.0
        if _t(icms_node, "nfe:vBCST") or _t(icms_node, "nfe:pICMSST") or _t(icms_node, "nfe:vICMSST"):
            st = True

    icms_destacado = v_bc is not None and p_icms is not None
    if icms_destacado:
        valor_operacao = v_bc
        aliquota = p_icms
    else:
        v_prod = _f(prod, "nfe:vProd")
        v_frete = _f(prod, "nfe:vFrete")
        v_seg = _f(prod, "nfe:vSeg")
        v_outro = _f(prod, "nfe:vOutro")
        v_desc = _f(prod, "nfe:vDesc")
        valor_operacao = v_prod + v_frete + v_seg + v_outro - v_desc
        aliquota = 0.0

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

    itens = []
    for det in inf_nfe.findall("nfe:det", NS):
        itens.append(_extrai_item(det, ide, emit, dest, arquivo_nome or path.name, chave))
    return itens
