"""
Cálculo do DIFAL de compras interestaduais destinadas ao Estado da Bahia
(uso, consumo ou ativo imobilizado) — Lei nº 7.014/1996, art. 17, XI e §6º.

A legislação baiana calcula o diferencial de alíquotas com base dupla
"por dentro": o ICMS de origem é deduzido do valor da operação, e a base
resultante é reajustada pela alíquota interna do Estado antes de aplicar
a diferença entre as alíquotas.

Para mercadorias sujeitas à substituição tributária (Cláusula 12ª do
Convênio ICMS 142/2018, mesma fórmula da antiga Cláusula 14ª do Convênio
52/2017), a fórmula é:
  ICMS ST DIFAL = [(V_oper - ICMS_origem) / (1 - ALQ_interna)] x ALQ_interna
                  - (V_oper x ALQ_interestadual)
"""

from dataclasses import dataclass

ALIQUOTA_INTERNA_BA = 0.205

# Convênio ICMS 52/91 (máquinas, aparelhos e equipamentos industriais,
# Anexo I) fixa carga tributária efetiva de 5,60% nas operações internas e
# nas interestaduais para uso/consumo/ativo — benefício internalizado pela
# Bahia no Art. 266 do RICMS-BA, uma das exceções em que o Estado reconhece
# a redução de base também para fins de cálculo do DIFAL.
ALIQUOTA_INTERNA_CONVENIO_5291 = 0.056


@dataclass
class ResultadoDifalItem:
    valor_operacao: float
    aliquota_interestadual: float               # usada para extrair o ICMS "por dentro" do valor da nota
    aliquota_interestadual_referencia: float    # usada na diferença final (Res. Senado 22/89 e 13/2012)
    icms_interestadual: float
    base_reduzida: float
    aliquota_interna: float
    base_reajustada: float
    diferenca_aliquotas: float
    difal: float
    formula: str  # "normal" ou "st"


def calcular_difal_item(valor_operacao: float, aliquota_interestadual: float,
                         substituicao_tributaria: bool,
                         aliquota_interna: float = ALIQUOTA_INTERNA_BA,
                         aliquota_interestadual_referencia: float | None = None) -> ResultadoDifalItem:
    """
    Calcula o DIFAL de um item conforme a fórmula normal (base dupla por
    dentro) ou a fórmula de substituição tributária, a depender de
    `substituicao_tributaria`.

    `aliquota_interestadual` extrai o ICMS embutido no valor da nota (no
    Regime Normal, é a própria alíquota efetivamente destacada; no Simples
    Nacional, é o percentual de crédito do art. 23 da LC 123/2006, ou 0%
    quando não informado). `aliquota_interestadual_referencia` é a taxa
    usada na diferença final — por padrão, igual à primeira, mas deve ser
    informada separadamente quando a nota não traz ICMS próprio destacado,
    caso em que a alíquota interestadual constitucional (Res. Senado 22/89
    e 13/2012) não pode ser lida diretamente do XML.
    """
    if not (0 <= aliquota_interna < 1):
        raise ValueError("Alíquota interna deve estar entre 0% e 100% (exclusive).")
    if aliquota_interestadual_referencia is None:
        aliquota_interestadual_referencia = aliquota_interestadual

    icms_interestadual = valor_operacao * aliquota_interestadual
    base_reduzida = valor_operacao - icms_interestadual
    base_reajustada = base_reduzida / (1 - aliquota_interna)
    diferenca = aliquota_interna - aliquota_interestadual_referencia

    if substituicao_tributaria:
        difal = base_reajustada * aliquota_interna - icms_interestadual
        formula = "st"
    else:
        difal = base_reajustada * diferenca
        formula = "normal"

    return ResultadoDifalItem(
        valor_operacao=valor_operacao,
        aliquota_interestadual=aliquota_interestadual,
        aliquota_interestadual_referencia=aliquota_interestadual_referencia,
        icms_interestadual=icms_interestadual,
        base_reduzida=base_reduzida,
        aliquota_interna=aliquota_interna,
        base_reajustada=base_reajustada,
        diferenca_aliquotas=diferenca,
        difal=max(difal, 0.0),
        formula=formula,
    )
