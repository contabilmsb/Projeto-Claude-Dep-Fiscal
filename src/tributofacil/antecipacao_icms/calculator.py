"""
Cálculo da antecipação parcial do ICMS (sem substituição tributária) sobre
aquisições interestaduais de mercadorias destinadas à comercialização —
Art. 12-A da Lei nº 7.014/1996; art. 289, §14 e §17, do RICMS-BA.

Diferente da substituição tributária por antecipação (art. 289, caput —
mercadorias do Anexo 1, com MVA específico por produto, que encerra a fase
de tributação), a antecipação parcial usa margens de valor agregado (MVA)
genéricas por categoria de mercadoria (§17) e é recuperável como crédito
pelo contribuinte do regime de conta-corrente fiscal (art. 309, II).

Fórmula (mesma sistemática nacional de ICMS-ST, aplicada à antecipação):
  MVA Ajustada = [(1 + MVA original) x (1 - ALQ inter) / (1 - ALQ intra)] - 1
  Base de Cálculo = Valor Comercial x (1 + MVA Ajustada)
  ICMS Antecipação = Base de Cálculo x ALQ intra - Valor Comercial x ALQ inter

Quando a alíquota interna (intra) for inferior à interestadual (inter) —
hipótese atípica —, usa-se a MVA original sem ajuste (§15 do art. 289).
"""

from dataclasses import dataclass

ALIQUOTA_INTERNA_BA = 0.205

# Percentuais de MVA original por categoria genérica de mercadoria, para
# antecipação de mercadorias NÃO enquadradas no regime de substituição
# tributária por antecipação (art. 289, §17, do RICMS-BA).
# "sem_mva" cobre o caso em que nenhuma MVA se aplica — a fórmula ainda
# ajusta a base pela diferença entre a alíquota interestadual e a interna
# (§14), só que sem nenhum acréscimo de margem sobre o valor de aquisição.
MVA_CATEGORIAS: dict[str, tuple[str, float]] = {
    "sem_mva":                  ("Sem MVA", 0.0),
    "generos_alimenticios":     ("Gêneros alimentícios", 0.50),
    "bebidas_alcoolicas":       ("Bebidas alcoólicas", 0.30),
    "bebidas_nao_alcoolicas":   ("Bebidas não alcoólicas", 0.70),
    "confeccoes_tecidos":       ("Confecções, tecidos e artefatos de tecidos", 0.40),
    "calcados":                 ("Calçados, cintos, bolsas e carteiras", 0.34),
    "perfumaria_cosmeticos":    ("Perfumaria, cosméticos e produtos de higiene pessoal", 0.60),
    "material_limpeza":         ("Material de limpeza", 0.40),
    "armarinho":                ("Artigos de armarinho", 0.90),
    "ferragens_loucas_vidros":  ("Ferragens, louças, vidros", 0.40),
    "materiais_eletricos":      ("Materiais elétricos", 0.60),
    "eletrodomesticos":         ("Eletrodomésticos e aparelhos eletrônicos", 0.20),
    "moveis":                   ("Móveis", 0.50),
    "material_informatica":     ("Material de informática", 0.20),
    "joias_relogios":           ("Joias, relógios e objetos de arte", 0.70),
    "outras_mercadorias":       ("Outras mercadorias", 0.40),
}


@dataclass
class ResultadoAntecipacaoItem:
    valor_comercial: float
    aliquota_interestadual: float
    mva_original: float
    mva_ajustada: float
    ajuste_aplicado: bool  # False quando ALQ intra < ALQ inter (§15 — usa MVA original)
    aliquota_interna: float
    base_calculo: float
    credito_origem: float
    antecipacao_devida: float


def calcular_mva_ajustada(mva_original: float, aliquota_interestadual: float, aliquota_interna: float) -> float:
    return ((1 + mva_original) * (1 - aliquota_interestadual) / (1 - aliquota_interna)) - 1


def calcular_item(
    valor_comercial: float,
    aliquota_interestadual: float,
    mva_original: float,
    aliquota_interna: float = ALIQUOTA_INTERNA_BA,
) -> ResultadoAntecipacaoItem:
    if not (0 <= aliquota_interna < 1):
        raise ValueError("Alíquota interna deve estar entre 0% e 100% (exclusive).")

    ajuste_aplicado = aliquota_interna > aliquota_interestadual
    mva_ajustada = (
        calcular_mva_ajustada(mva_original, aliquota_interestadual, aliquota_interna)
        if ajuste_aplicado
        else mva_original
    )

    base_calculo = valor_comercial * (1 + mva_ajustada)
    credito_origem = valor_comercial * aliquota_interestadual
    antecipacao_devida = base_calculo * aliquota_interna - credito_origem

    return ResultadoAntecipacaoItem(
        valor_comercial=valor_comercial,
        aliquota_interestadual=aliquota_interestadual,
        mva_original=mva_original,
        mva_ajustada=mva_ajustada,
        ajuste_aplicado=ajuste_aplicado,
        aliquota_interna=aliquota_interna,
        base_calculo=base_calculo,
        credito_origem=credito_origem,
        antecipacao_devida=max(antecipacao_devida, 0.0),
    )
