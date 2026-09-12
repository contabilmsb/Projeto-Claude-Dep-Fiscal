"""
Leitura de arquivos XML de NF-e para apuração da antecipação parcial do ICMS
(sem substituição tributária) sobre aquisições interestaduais de mercadorias
destinadas à comercialização no Estado da Bahia.

Base legal: Art. 12-A da Lei nº 7.014/1996; art. 289, §14 e §17, do RICMS-BA
(Decreto nº 13.780/2012).

Diferente do DIFAL (que trata de compras para uso, consumo ou ativo
imobilizado), a antecipação parcial incide sobre mercadorias adquiridas para
revenda — por isso a base de cálculo aqui é sempre o valor comercial do item
(vProd + frete + seguro + outras despesas − desconto), sem a fórmula de
"base dupla por dentro" do DIFAL.

Para cada item (<det>) extrai:
  - a alíquota do ICMS embutido no preço, usada como crédito na fórmula da
    antecipação: no Regime Normal, a própria alíquota (pICMS) destacada no
    XML; no Simples Nacional, o percentual de crédito informado (pCredSN,
    art. 23 da LC 123/2006), ou 0% quando não informado.
  - sinalizações (avisos) para os casos em que a nota não parece ser uma
    aquisição interestadual para revenda: operação interna (mesma UF),
    destino diferente da Bahia, ou CFOP típico de uso/consumo (que é caso de
    DIFAL, não de antecipação).
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

NS = {"nfe": "http://www.portalfiscal.inf.br/nfe"}

# CFOPs de saída tipicamente usados para uso/consumo ou ativo imobilizado
# (não para revenda) — o CFOP no XML é sempre o do emitente (saída: 5.xxx
# interna, 6.xxx interestadual, 7.xxx exterior), nunca o de entrada do
# destinatário. Sinaliza para revisão, pois esses casos são de DIFAL.
_CFOP_USO_CONSUMO_ATIVO = {
    "5551", "6551", "7551",  # venda de bem do ativo imobilizado
    "5556", "6556", "7556",  # venda de material de uso ou consumo
}


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
class ItemAntecipacao:
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
    ncm: str
    n_item: str
    descricao_produto: str
    valor_comercial: float        # vProd + frete + seguro + outros - desconto
    aliquota_interestadual: float  # ICMS embutido no preço (pICMS, ou pCredSN no Simples Nacional)
    icms_destacado: bool
    percentual_credito_simples: float | None
    cfop_uso_consumo: bool        # CFOP típico de uso/consumo/ativo — provável caso de DIFAL, não antecipação


def _regime(crt: str | None) -> str:
    return "Simples Nacional" if crt == "1" else "Normal"


def _extrai_item(det, ide, emit, dest, arquivo: str, chave: str) -> ItemAntecipacao:
    prod = det.find("nfe:prod", NS)
    imposto = det.find("nfe:imposto", NS)
    icms = imposto.find("nfe:ICMS", NS) if imposto is not None else None
    icms_node = next(iter(icms), None) if icms is not None else None

    v_icms = None
    p_icms = None
    p_cred_sn = None
    if icms_node is not None:
        v_icms_txt = _t(icms_node, "nfe:vICMS")
        if v_icms_txt is not None:
            v_icms = float(v_icms_txt)
        p_icms_txt = _t(icms_node, "nfe:pICMS")
        if p_icms_txt is not None:
            p_icms = float(p_icms_txt)
        p_cred_sn_txt = _t(icms_node, "nfe:pCredSN")
        if p_cred_sn_txt is not None:
            p_cred_sn = float(p_cred_sn_txt)

    v_prod = _f(prod, "nfe:vProd")
    v_frete = _f(prod, "nfe:vFrete")
    v_seg = _f(prod, "nfe:vSeg")
    v_outro = _f(prod, "nfe:vOutro")
    v_desc = _f(prod, "nfe:vDesc")
    valor_comercial = v_prod + v_frete + v_seg + v_outro - v_desc

    icms_destacado = v_icms is not None
    if icms_destacado:
        aliquota = (p_icms / 100.0) if p_icms is not None else ((v_icms / valor_comercial) if valor_comercial else 0.0)
    else:
        aliquota = (p_cred_sn / 100.0) if p_cred_sn is not None else 0.0

    crt = _t(emit, "nfe:CRT")
    cfop = _t(prod, "nfe:CFOP", "") or ""

    return ItemAntecipacao(
        arquivo=arquivo,
        chave_nfe=chave,
        numero_nf=_t(ide, "nfe:nNF", "") or "",
        data_emissao=(_t(ide, "nfe:dhEmi") or _t(ide, "nfe:dEmi") or ""),
        cnpj_emitente=_t(emit, "nfe:CNPJ", "") or "",
        nome_emitente=_t(emit, "nfe:xNome", "") or "",
        uf_origem=_t(emit, "nfe:enderEmit/nfe:UF", "") or "",
        uf_destino=_t(dest, "nfe:enderDest/nfe:UF", "") or "",
        regime_emitente=_regime(crt),
        cfop=cfop,
        ncm=_t(prod, "nfe:NCM", "") or "",
        n_item=det.get("nItem", ""),
        descricao_produto=_t(prod, "nfe:xProd", "") or "",
        valor_comercial=valor_comercial,
        aliquota_interestadual=aliquota,
        icms_destacado=icms_destacado,
        percentual_credito_simples=p_cred_sn,
        cfop_uso_consumo=cfop in _CFOP_USO_CONSUMO_ATIVO,
    )


def parse_nfe_xml(path: Path, arquivo_nome: str | None = None) -> list[ItemAntecipacao]:
    """Extrai um ItemAntecipacao por item (<det>) do XML de NF-e informado."""
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
