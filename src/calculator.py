"""
Lógica de apuração PIS/COFINS — regime cumulativo (Lei 9.718/98).

Bases legais relevantes:
  - Lei 9.718/1998: institui a base de cálculo e alíquotas no regime cumulativo
  - Art. 3º § 1º: base = receita bruta (regime caixa para empresas optantes)
  - IN RFB 459/2004: retenção na fonte de PIS/COFINS/CSLL por órgãos públicos
"""

import pandas as pd
from dataclasses import dataclass, field


@dataclass
class ApuracaoTributo:
    nome: str
    aliquota: float
    base_calculo: float = 0.0
    valor_apurado: float = 0.0
    retencao_fonte: float = 0.0
    valor_a_pagar: float = 0.0
    # Detalhamento da base
    receita_recebida: float = 0.0
    juros_recebidos: float = 0.0
    descontos: float = 0.0
    exclusoes: float = 0.0


@dataclass
class ResultadoApuracao:
    competencia: str
    cofins: ApuracaoTributo = field(default_factory=lambda: ApuracaoTributo("COFINS", 0.03))
    pis:    ApuracaoTributo = field(default_factory=lambda: ApuracaoTributo("PIS",    0.0065))
    # Retenções complementares (informativo)
    csll_retida: float = 0.0
    irrf_retido:  float = 0.0
    total_recebido: float = 0.0
    total_juros:    float = 0.0


def calcular(dados: dict[str, pd.DataFrame], competencia: str,
             cofins_rate: float, pis_rate: float) -> ResultadoApuracao:
    """
    Executa a apuração PIS e COFINS para a competência informada.

    Lógica (regime cumulativo — base caixa):
      Base = Receitas recebidas de clientes + Juros/Multas recebidos
      Valor apurado = Base × alíquota
      Valor a pagar = Valor apurado − Retenção na fonte

    Parâmetros
    ----------
    dados : dict de DataFrames carregados por readers.load_all()
    """
    resultado = ResultadoApuracao(competencia=competencia)

    # ── Totais por fonte ──────────────────────────────────────────────────────
    total_recebido  = dados["recebidas"]["recebido"].sum()
    total_juros     = dados["juros"]["juros"].sum() if not dados["juros"].empty else 0.0
    cofins_retido   = dados["cofins_ret"]["cofins_retido"].sum()
    pis_retido      = dados["pis_ret"]["pis_retido"].sum()
    csll_retida     = dados["csll_ret"]["csll_retido"].sum()
    irrf_retido     = dados["irrf"]["irrf"].sum()

    resultado.total_recebido = total_recebido
    resultado.total_juros    = total_juros
    resultado.csll_retida    = csll_retida
    resultado.irrf_retido    = irrf_retido

    # ── Base Líquida ──────────────────────────────────────────────────────────
    # Recebido líquido + retenções (reconstitui a receita bruta faturada)
    # Juros/multas recebidos são excluídos da base PIS/COFINS
    base = total_recebido + cofins_retido + pis_retido + csll_retida + irrf_retido - total_juros

    # ── COFINS ────────────────────────────────────────────────────────────────
    vr_cofins    = base * cofins_rate
    cofins_pagar = max(vr_cofins - cofins_retido, 0.0)

    resultado.cofins = ApuracaoTributo(
        nome="COFINS",
        aliquota=cofins_rate,
        receita_recebida=total_recebido,
        juros_recebidos=total_juros,
        base_calculo=base,
        valor_apurado=vr_cofins,
        retencao_fonte=cofins_retido,
        valor_a_pagar=cofins_pagar,
    )

    # ── PIS ───────────────────────────────────────────────────────────────────
    vr_pis    = base * pis_rate
    pis_pagar = max(vr_pis - pis_retido, 0.0)

    resultado.pis = ApuracaoTributo(
        nome="PIS",
        aliquota=pis_rate,
        receita_recebida=total_recebido,
        juros_recebidos=total_juros,
        base_calculo=base,
        valor_apurado=vr_pis,
        retencao_fonte=pis_retido,
        valor_a_pagar=pis_pagar,
    )

    return resultado
