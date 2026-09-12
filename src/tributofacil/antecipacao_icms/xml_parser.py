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

Para cada item (<det>) extrai a alíquota interestadual (o "ALQ inter" do §14
do art. 289 — usada tanto na MVA ajustada quanto como crédito de origem a
deduzir):
  - Regime Normal, com ICMS próprio destacado: a alíquota (pICMS) informada
    no próprio item — é a que o remetente efetivamente aplicou.
  - Simples Nacional, sem ICMS próprio destacado: a alíquota interestadual
    constitucional (Res. Senado 22/89 e 13/2012), obtida a partir da UF do
    fornecedor e da UF de destino — nos termos do art. 269, VIII, do
    RICMS-BA ("... o valor resultante da aplicação do percentual da
    alíquota interestadual prevista na legislação da unidade da Federação
    de origem sobre o valor da operação constante no documento fiscal").

Também sinaliza (via campos booleanos, para o chamador gerar avisos) os
casos em que a nota não parece ser uma aquisição interestadual para
revenda: operação interna (mesma UF), destino diferente da Bahia, ou CFOP
típico de uso/consumo (que é caso de DIFAL, não de antecipação).
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from src.tributofacil.aliquota_interestadual import aliquota_referencia_resolucao_2289, eh_origem_importada

NS = {"nfe": "http://www.portalfiscal.inf.br/nfe"}

# CFOPs de saída tipicamente usados para uso/consumo ou ativo imobilizado
# (não para revenda) — o CFOP no XML é sempre o do emitente (saída: 5.xxx
# interna, 6.xxx interestadual, 7.xxx exterior), nunca o de entrada do
# destinatário. Sinaliza para revisão, pois esses casos são de DIFAL.
_CFOP_USO_CONSUMO_ATIVO = {
    "5551", "6551", "7551",  # venda de bem do ativo imobilizado
    "5556", "6556", "7556",  # venda de material de uso ou consumo
}

# Descrição do campo `orig` do ICMS (Origem da Mercadoria), conforme layout da NF-e.
_DESCRICAO_ORIGEM = {
    "0": "Nacional, exceto as indicadas nos códigos 3, 4, 5 e 8",
    "1": "Estrangeira — Importação direta, exceto a indicada no código 6",
    "2": "Estrangeira — Adquirida no mercado interno, exceto a indicada no código 7",
    "3": "Nacional, com Conteúdo de Importação superior a 40% e inferior ou igual a 70%",
    "4": "Nacional, produção conforme processos produtivos básicos",
    "5": "Nacional, com Conteúdo de Importação inferior ou igual a 40%",
    "6": "Estrangeira — Importação direta, sem similar nacional (lista CAMEX)",
    "7": "Estrangeira — Adquirida no mercado interno, sem similar nacional (lista CAMEX)",
    "8": "Nacional, com Conteúdo de Importação superior a 70%",
}


def _descricao_origem(orig: str | None) -> str:
    if orig is None:
        return ""
    return f"{orig} - {_DESCRICAO_ORIGEM.get(orig, 'desconhecida')}"


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
    cst_csosn: str                # ex.: "CST 00" ou "CSOSN 102"
    origem_mercadoria: str        # ex.: "1 - Estrangeira — Importação direta..." (campo `orig` do ICMS)
    n_item: str
    descricao_produto: str
    valor_comercial: float        # vProd + frete + seguro + outros - desconto
    aliquota_interestadual: float  # "ALQ inter" do §14 do art. 289
    origem_aliquota: str          # como a alíquota foi obtida (para observações)
    icms_destacado: bool
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
    orig_mercadoria = None
    cst_csosn = ""
    if icms_node is not None:
        orig_mercadoria = _t(icms_node, "nfe:orig")
        v_icms_txt = _t(icms_node, "nfe:vICMS")
        if v_icms_txt is not None:
            v_icms = float(v_icms_txt)
        p_icms_txt = _t(icms_node, "nfe:pICMS")
        if p_icms_txt is not None:
            p_icms = float(p_icms_txt)
        cst_txt = _t(icms_node, "nfe:CST")
        csosn_txt = _t(icms_node, "nfe:CSOSN")
        if cst_txt is not None:
            cst_csosn = f"CST {cst_txt}"
        elif csosn_txt is not None:
            cst_csosn = f"CSOSN {csosn_txt}"

    v_prod = _f(prod, "nfe:vProd")
    v_frete = _f(prod, "nfe:vFrete")
    v_seg = _f(prod, "nfe:vSeg")
    v_outro = _f(prod, "nfe:vOutro")
    v_desc = _f(prod, "nfe:vDesc")
    valor_comercial = v_prod + v_frete + v_seg + v_outro - v_desc

    uf_origem = _t(emit, "nfe:enderEmit/nfe:UF", "") or ""
    uf_destino = _t(dest, "nfe:enderDest/nfe:UF", "") or ""

    icms_destacado = v_icms is not None
    if eh_origem_importada(orig_mercadoria):
        # Res. Senado 13/2012: 4% é constitucional para mercadoria importada
        # ou com conteúdo de importação > 40% — prevalece sobre qualquer
        # alíquota destacada no XML, inclusive em caso de divergência.
        aliquota = 0.04
        origem_aliquota = "Alíquota especial de 4% para mercadoria importada (Res. Senado 13/2012, campo 'orig' do ICMS)"
        if icms_destacado and p_icms is not None and abs(p_icms / 100.0 - 0.04) > 0.001:
            origem_aliquota += (
                f" — ATENÇÃO: pICMS destacado no XML ({p_icms:.2f}%) diverge do exigido, confira a nota"
            )
    elif icms_destacado and p_icms is not None:
        aliquota = p_icms / 100.0
        origem_aliquota = "Destacada no XML (pICMS do item)"
    elif icms_destacado and valor_comercial:
        aliquota = v_icms / valor_comercial
        origem_aliquota = "Calculada a partir do ICMS destacado no item (vICMS / valor comercial)"
    else:
        aliquota = aliquota_referencia_resolucao_2289(uf_origem, uf_destino, orig_mercadoria)
        origem_aliquota = (
            "Alíquota interestadual constitucional por UF de origem/destino (Res. Senado 22/89) — "
            "nota sem ICMS próprio destacado (art. 269, VIII, do RICMS-BA)"
        )

    crt = _t(emit, "nfe:CRT")
    cfop = _t(prod, "nfe:CFOP", "") or ""

    return ItemAntecipacao(
        arquivo=arquivo,
        chave_nfe=chave,
        numero_nf=_t(ide, "nfe:nNF", "") or "",
        data_emissao=(_t(ide, "nfe:dhEmi") or _t(ide, "nfe:dEmi") or ""),
        cnpj_emitente=_t(emit, "nfe:CNPJ", "") or "",
        nome_emitente=_t(emit, "nfe:xNome", "") or "",
        uf_origem=uf_origem,
        uf_destino=uf_destino,
        regime_emitente=_regime(crt),
        cfop=cfop,
        ncm=_t(prod, "nfe:NCM", "") or "",
        cst_csosn=cst_csosn,
        origem_mercadoria=_descricao_origem(orig_mercadoria),
        n_item=det.get("nItem", ""),
        descricao_produto=_t(prod, "nfe:xProd", "") or "",
        valor_comercial=valor_comercial,
        aliquota_interestadual=aliquota,
        origem_aliquota=origem_aliquota,
        icms_destacado=icms_destacado,
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
