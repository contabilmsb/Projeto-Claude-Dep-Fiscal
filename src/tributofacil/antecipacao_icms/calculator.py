"""
Cálculo da antecipação parcial do ICMS (sem substituição tributária) sobre
aquisições interestaduais de mercadorias destinadas à comercialização —
Art. 12-A da Lei nº 7.014/1996; art. 289 do RICMS-BA.

Fórmula: a antecipação devida é a diferença entre o ICMS pela alíquota
interna da Bahia e o ICMS pela alíquota interestadual, ambos calculados
sobre o valor comercial do item — sem margem de valor agregado (MVA):

  ICMS Interno BA        = Valor Comercial x ALQ intra
  ICMS Interestadual      = Valor Comercial x ALQ inter
  Antecipação Devida     = ICMS Interno BA - ICMS Interestadual
"""

from dataclasses import dataclass

ALIQUOTA_INTERNA_BA = 0.205


@dataclass
class ResultadoAntecipacaoItem:
    valor_comercial: float
    aliquota_interestadual: float
    aliquota_interna: float
    icms_interestadual: float
    icms_interno: float
    antecipacao_devida: float


def calcular_item(
    valor_comercial: float,
    aliquota_interestadual: float,
    aliquota_interna: float = ALIQUOTA_INTERNA_BA,
) -> ResultadoAntecipacaoItem:
    if not (0 <= aliquota_interna < 1):
        raise ValueError("Alíquota interna deve estar entre 0% e 100% (exclusive).")

    icms_interestadual = valor_comercial * aliquota_interestadual
    icms_interno = valor_comercial * aliquota_interna
    antecipacao_devida = icms_interno - icms_interestadual

    return ResultadoAntecipacaoItem(
        valor_comercial=valor_comercial,
        aliquota_interestadual=aliquota_interestadual,
        aliquota_interna=aliquota_interna,
        icms_interestadual=icms_interestadual,
        icms_interno=icms_interno,
        antecipacao_devida=max(antecipacao_devida, 0.0),
    )
