"""
Leitura de arquivos XML de NF-e para apuração do DIFAL de compras
destinadas ao Estado da Bahia (uso, consumo ou ativo imobilizado).

Base legal: Lei nº 7.014/1996, art. 4º XV e art. 17 XI e §6º.

Para cada item (<det>) da NF-e, extrai o valor da operação e as
alíquotas relevantes para a fórmula de "base dupla por dentro":

  - Regime Normal, com ICMS próprio destacado (vICMS, em ICMS00, ICMS10,
    ICMS20 etc.): por padrão usa a própria base do ICMS (vBC) como valor
    da operação, e a alíquota efetiva é vICMS / vBC — a mesma base que o
    remetente usou para calcular o imposto. Isso importa porque vBC pode
    ser maior que vProd (ex.: quando o IPI integra a base do ICMS por a
    operação não ser entre contribuintes para revenda/industrialização,
    Art. 13 §2º da LC 87/96) — usar vProd nesses casos infla artificial-
    mente a alíquota efetiva extraída. A exceção é quando há redução de
    base (pRedBC): a Bahia não reconhece a maioria das reduções para fins
    de DIFAL (usa-se o valor comercial pleno, vProd + acessórios, com a
    alíquota interna cheia), salvo os benefícios que ela mesma incorpora
    ao seu próprio regulamento — hoje, o Convênio ICMS 52/91 (ver abaixo).

  - Simples Nacional, sem ICMS próprio destacado (grupo ICMSSNxxx): o
    fornecedor não recolhe ICMS pela sistemática normal, mas o art. 23 da
    LC 123/2006 o obriga a informar, quando aplicável (CSOSN 101/201), o
    percentual de crédito de ICMS que o destinatário pode aproveitar
    (campo estruturado pCredSN) — esse percentual é o que se extrai "por
    dentro" do valor da nota (ou 0%, de forma conservadora, quando o
    CSOSN não permite crédito ou o campo não vem informado). Isso NÃO
    substitui a alíquota interestadual de referência usada na diferença
    final: essa é constitucional (Resolução do Senado nº 22/89, com a
    alíquota de 4% da Resolução nº 13/2012 para bens importados/com
    conteúdo de importação > 40%) e vale igual para qualquer regime do
    remetente — por isso é sempre calculada a partir das UFs de origem/
    destino quando a nota não traz ICMS próprio destacado.

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

# Resolução do Senado Federal nº 22/1989 — alíquota interestadual de referência
# do ICMS, por região da UF de origem.
_REGIAO_UF = {
    "AC": "N", "AP": "N", "AM": "N", "PA": "N", "RO": "N", "RR": "N", "TO": "N",
    "AL": "NE", "BA": "NE", "CE": "NE", "MA": "NE", "PB": "NE", "PE": "NE", "PI": "NE", "RN": "NE", "SE": "NE",
    "DF": "CO", "GO": "CO", "MT": "CO", "MS": "CO",
    "ES": "ES",
    "SP": "SE", "RJ": "SE", "MG": "SE",
    "PR": "S", "SC": "S", "RS": "S",
}
_REGIOES_DESTINO_ALIQ_7 = {"N", "NE", "CO", "ES"}
# Resolução do Senado Federal nº 13/2012 — 4% para bens/mercadorias
# importados do exterior ou com conteúdo de importação > 40% (campo `orig`
# do ICMS: 1, 2, 3, 6, 7 ou 8).
_ORIG_IMPORTADO_4PCT = {"1", "2", "3", "6", "7", "8"}


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
    valor_operacao: float          # base efetivamente usada no cálculo (vBC, ou vProd + acessórios nos casos de redução)
    valor_comercial: float         # vProd + acessórios (frete/seguro/outras despesas - desconto), sempre informativo
    aliquota_interestadual: float  # taxa usada para extrair o ICMS "por dentro" da nota (decimal)
    aliquota_interestadual_referencia: float  # taxa constitucional (Res. 22/89) usada na diferença final
    icms_destacado: bool           # False quando não há ICMS próprio destacado no XML (Simples Nacional)
    percentual_credito_simples: float | None  # pCredSN informado pelo Simples Nacional (CSOSN 101/201), se houver
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


def _aliquota_referencia_resolucao_2289(uf_origem: str, uf_destino: str, orig_mercadoria: str | None) -> float:
    """Alíquota interestadual constitucional (Res. Senado 22/89 e 13/2012),
    usada como referência quando a nota não traz ICMS próprio destacado
    (Simples Nacional) — independe do regime tributário do remetente."""
    if orig_mercadoria in _ORIG_IMPORTADO_4PCT:
        return 0.04
    regiao_origem = _REGIAO_UF.get(uf_origem)
    regiao_destino = _REGIAO_UF.get(uf_destino)
    if regiao_origem in ("S", "SE") and regiao_destino in _REGIOES_DESTINO_ALIQ_7:
        return 0.07
    return 0.12


def _extrai_item(det, ide, emit, dest, arquivo: str, chave: str, nota_convenio_5291: bool) -> ItemDifal:
    prod = det.find("nfe:prod", NS)
    imposto = det.find("nfe:imposto", NS)
    icms = imposto.find("nfe:ICMS", NS) if imposto is not None else None
    icms_node = next(iter(icms), None) if icms is not None else None

    v_bc = None
    v_icms = None
    st = False
    p_red_bc = None
    p_cred_sn = None
    orig_mercadoria = None
    if icms_node is not None:
        orig_mercadoria = _t(icms_node, "nfe:orig")
        v_bc_txt = _t(icms_node, "nfe:vBC")
        if v_bc_txt is not None:
            v_bc = float(v_bc_txt)
        v_icms_txt = _t(icms_node, "nfe:vICMS")
        if v_icms_txt is not None:
            v_icms = float(v_icms_txt)
        p_red_bc_txt = _t(icms_node, "nfe:pRedBC")
        if p_red_bc_txt is not None:
            p_red_bc = float(p_red_bc_txt)
        p_cred_sn_txt = _t(icms_node, "nfe:pCredSN")
        if p_cred_sn_txt is not None:
            p_cred_sn = float(p_cred_sn_txt)
        if _t(icms_node, "nfe:vBCST") or _t(icms_node, "nfe:pICMSST") or _t(icms_node, "nfe:vICMSST"):
            st = True

    v_prod = _f(prod, "nfe:vProd")
    v_frete = _f(prod, "nfe:vFrete")
    v_seg = _f(prod, "nfe:vSeg")
    v_outro = _f(prod, "nfe:vOutro")
    v_desc = _f(prod, "nfe:vDesc")
    valor_comercial = v_prod + v_frete + v_seg + v_outro - v_desc

    icms_destacado = v_icms is not None
    uf_origem = _t(emit, "nfe:enderEmit/nfe:UF", "") or ""
    uf_destino = _t(dest, "nfe:enderDest/nfe:UF", "") or ""
    convenio_5291 = nota_convenio_5291 and p_red_bc is not None
    reducao_nao_reconhecida = (p_red_bc is not None) and not convenio_5291

    if icms_destacado:
        if convenio_5291 or reducao_nao_reconhecida:
            # Base reduzida na origem: a Bahia não reconhece a redução (ou,
            # quando reconhece — Convênio 52/91 —, aplica sua própria
            # alíquota interna reduzida sobre o valor pleno), então
            # reconstrói o valor comercial total do item.
            valor_operacao = valor_comercial
        else:
            # Usa a mesma base que o remetente usou para calcular o ICMS
            # (pode ser maior que vProd quando o IPI integra a base —
            # Art. 13 §2º da LC 87/96), para que a alíquota efetiva
            # extraída "por dentro" reflete fielmente o que foi recolhido.
            valor_operacao = v_bc if v_bc is not None else valor_comercial
        aliquota = (v_icms / valor_operacao) if valor_operacao > 0 else 0.0
        aliquota_referencia = aliquota
    else:
        # Simples Nacional: usa o crédito informado (art. 23, LC 123/2006)
        # só para extrair o ICMS embutido no preço; a alíquota de
        # referência da diferença é sempre a constitucional (Res. 22/89),
        # independente do regime do remetente.
        valor_operacao = valor_comercial
        aliquota = (p_cred_sn / 100.0) if p_cred_sn is not None else 0.0
        aliquota_referencia = _aliquota_referencia_resolucao_2289(uf_origem, uf_destino, orig_mercadoria)

    crt = _t(emit, "nfe:CRT")

    return ItemDifal(
        arquivo=arquivo,
        chave_nfe=chave,
        numero_nf=_t(ide, "nfe:nNF", "") or "",
        data_emissao=(_t(ide, "nfe:dhEmi") or _t(ide, "nfe:dEmi") or ""),
        cnpj_emitente=_t(emit, "nfe:CNPJ", "") or "",
        nome_emitente=_t(emit, "nfe:xNome", "") or "",
        uf_origem=uf_origem,
        uf_destino=uf_destino,
        regime_emitente=_regime(crt),
        cfop=_t(prod, "nfe:CFOP", "") or "",
        n_item=det.get("nItem", ""),
        descricao_produto=_t(prod, "nfe:xProd", "") or "",
        valor_operacao=valor_operacao,
        valor_comercial=valor_comercial,
        aliquota_interestadual=aliquota,
        aliquota_interestadual_referencia=aliquota_referencia,
        icms_destacado=icms_destacado,
        percentual_credito_simples=p_cred_sn,
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
