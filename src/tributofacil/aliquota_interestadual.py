"""
Alíquota interestadual constitucional de referência do ICMS (Resolução do
Senado Federal nº 22/1989 e nº 13/2012), compartilhada pelos módulos que
apuram ICMS sobre aquisições interestaduais (Difal Bahia, Antecipação de
ICMS) — usada quando a nota não permite extrair a alíquota diretamente do
item (ex.: fornecedor optante pelo Simples Nacional, sem ICMS destacado).
"""

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


def eh_origem_importada(orig_mercadoria: str | None) -> bool:
    """True quando o campo `orig` do ICMS indica mercadoria importada do
    exterior ou com conteúdo de importação > 40% (Res. Senado 13/2012)."""
    return orig_mercadoria in _ORIG_IMPORTADO_4PCT


def aliquota_referencia_resolucao_2289(uf_origem: str, uf_destino: str, orig_mercadoria: str | None) -> float:
    """Alíquota interestadual constitucional (Res. Senado 22/89 e 13/2012),
    aplicável independentemente do regime tributário do remetente."""
    if eh_origem_importada(orig_mercadoria):
        return 0.04
    regiao_origem = _REGIAO_UF.get(uf_origem)
    regiao_destino = _REGIAO_UF.get(uf_destino)
    if regiao_origem in ("S", "SE") and regiao_destino in _REGIOES_DESTINO_ALIQ_7:
        return 0.07
    return 0.12
