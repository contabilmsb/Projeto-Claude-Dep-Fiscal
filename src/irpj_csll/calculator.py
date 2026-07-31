"""
Lógica de apuração IRPJ/CSLL — regime de Lucro Presumido, apuração
trimestral, base caixa.

Bases legais relevantes:
  - Lei 9.249/1995, art. 15 e art. 20: percentuais de presunção
  - Lei 9.430/1996, art. 25, II: demais receitas/ganhos incluídos a 100% na base
  - Lei 9.430/1996, art. 3º §1º: adicional de IRPJ
  - Lei 9.430/1996, art. 5º: parcelamento do IRPJ/CSLL em até 3 quotas mensais
  - IN RFB 1.022/2010, art. 55, I: aproveitamento do IRRF sobre aplicações
    financeiras como dedução do IRPJ devido

Os percentuais de presunção de "Revendas" (8,8% IRPJ / 13,2% CSLL) são um
ajuste intencional da contabilidade sobre os percentuais padrão da lei
(8%/12%) — ver src/irpj_csll/config.py.
"""

from dataclasses import dataclass, field

from . import config as cfg


@dataclass
class ComponenteMes:
    """Componentes de um mês, prontos para consolidação trimestral."""
    competencia: str                    # "MM/AAAA"
    revenda_base: float = 0.0           # base_liquida reaproveitada do PIS/COFINS
    servicos_base: float = 0.0          # não utilizado atualmente pela empresa
    aplicacao_financeira: float = 0.0
    variacao_cambial: float = 0.0
    juros_recebidos: float = 0.0        # reaproveitado do PIS/COFINS (total_juros)
    ganho_capital: float = 0.0
    irrf_cliente: float = 0.0           # reaproveitado do PIS/COFINS (irrf_retido)
    irrf_aplicacao: float = 0.0         # extraído do novo IRRF.xlsx
    csll_retida: float = 0.0            # reaproveitado do PIS/COFINS (csll_retida)


@dataclass
class ApuracaoTributo:
    nome: str
    base_calculo: float = 0.0
    valor_apurado: float = 0.0
    adicional: float = 0.0
    valor_devido: float = 0.0
    deducoes: float = 0.0
    valor_a_pagar: float = 0.0
    base_revenda: float = 0.0
    base_servicos: float = 0.0
    base_outras_receitas: float = 0.0


@dataclass
class Parcela:
    numero: int
    valor: float


@dataclass
class ResultadoTrimestre:
    ano: int
    trimestre: int
    competencias: list = field(default_factory=list)
    irpj: ApuracaoTributo = None
    csll: ApuracaoTributo = None
    parcelas_irpj: list = field(default_factory=list)
    parcelas_csll: list = field(default_factory=list)


def trimestre_de(mes: int) -> int:
    return (mes - 1) // 3 + 1


def meses_do_trimestre(trimestre: int) -> list[int]:
    inicio = (trimestre - 1) * 3 + 1
    return [inicio, inicio + 1, inicio + 2]


def calcular_mes(competencia: str, *, revenda_base: float, aplicacao_financeira: float,
                  variacao_cambial: float, juros_recebidos: float, irrf_cliente: float,
                  irrf_aplicacao: float, csll_retida: float,
                  servicos_base: float = 0.0, ganho_capital: float = 0.0) -> ComponenteMes:
    return ComponenteMes(
        competencia=competencia,
        revenda_base=revenda_base,
        servicos_base=servicos_base,
        aplicacao_financeira=aplicacao_financeira,
        variacao_cambial=variacao_cambial,
        juros_recebidos=juros_recebidos,
        ganho_capital=ganho_capital,
        irrf_cliente=irrf_cliente,
        irrf_aplicacao=irrf_aplicacao,
        csll_retida=csll_retida,
    )


def _montar_parcelas(valor_devido: float) -> list[Parcela]:
    if valor_devido <= 0:
        return []

    n = cfg.N_PARCELAS
    while n > 1 and valor_devido / n < cfg.VALOR_MINIMO_PARCELA:
        n -= 1

    valor = round(valor_devido / n, 2)
    return [Parcela(numero=i, valor=valor) for i in range(1, n + 1)]


def _apurar(meses: list[ComponenteMes], limite_adicional: float) -> tuple[ApuracaoTributo, ApuracaoTributo]:
    """Apura IRPJ e CSLL sobre a soma dos componentes informados (1 mês ou o trimestre inteiro)."""
    soma_revenda = sum(m.revenda_base for m in meses)
    soma_servicos = sum(m.servicos_base for m in meses)
    soma_outras = sum(
        m.aplicacao_financeira + m.variacao_cambial + m.juros_recebidos + m.ganho_capital
        for m in meses
    )
    soma_irrf_cliente = sum(m.irrf_cliente for m in meses)
    soma_irrf_aplicacao = sum(m.irrf_aplicacao for m in meses)
    soma_csll_retida = sum(m.csll_retida for m in meses)

    # ── IRPJ ──────────────────────────────────────────────────────────────────
    base_irpj_revenda = soma_revenda * cfg.IRPJ_REVENDA_RATE
    base_irpj_servicos = soma_servicos * cfg.IRPJ_SERVICOS_RATE
    base_irpj_outras = soma_outras * cfg.OUTRAS_RECEITAS_RATE
    base_irpj = base_irpj_revenda + base_irpj_servicos + base_irpj_outras

    irpj_apurado = base_irpj * cfg.IRPJ_RATE
    excedente = max(base_irpj - limite_adicional, 0.0)
    irpj_adicional = excedente * cfg.IRPJ_ADICIONAL_RATE
    irpj_devido = irpj_apurado + irpj_adicional
    irpj_deducoes = soma_irrf_cliente + soma_irrf_aplicacao
    irpj_a_pagar = max(irpj_devido - irpj_deducoes, 0.0)

    irpj = ApuracaoTributo(
        nome="IRPJ",
        base_calculo=base_irpj,
        valor_apurado=irpj_apurado,
        adicional=irpj_adicional,
        valor_devido=irpj_devido,
        deducoes=irpj_deducoes,
        valor_a_pagar=irpj_a_pagar,
        base_revenda=base_irpj_revenda,
        base_servicos=base_irpj_servicos,
        base_outras_receitas=base_irpj_outras,
    )

    # ── CSLL (sem adicional; sem retenção sobre aplicação financeira) ───────────
    base_csll_revenda = soma_revenda * cfg.CSLL_REVENDA_RATE
    base_csll_servicos = soma_servicos * cfg.CSLL_SERVICOS_RATE
    base_csll_outras = soma_outras * cfg.OUTRAS_RECEITAS_RATE
    base_csll = base_csll_revenda + base_csll_servicos + base_csll_outras

    csll_apurada = base_csll * cfg.CSLL_RATE
    csll_deducoes = soma_csll_retida
    csll_a_pagar = max(csll_apurada - csll_deducoes, 0.0)

    csll = ApuracaoTributo(
        nome="CSLL",
        base_calculo=base_csll,
        valor_apurado=csll_apurada,
        adicional=0.0,
        valor_devido=csll_apurada,
        deducoes=csll_deducoes,
        valor_a_pagar=csll_a_pagar,
        base_revenda=base_csll_revenda,
        base_servicos=base_csll_servicos,
        base_outras_receitas=base_csll_outras,
    )

    return irpj, csll


def apurar_mes(componente: ComponenteMes) -> tuple[ApuracaoTributo, ApuracaoTributo]:
    """
    Apuração informativa de um único mês (mesmas alíquotas/deduções da apuração
    trimestral, com o limite do adicional de IRPJ proporcional a 1 mês).

    O IRPJ/CSLL do Lucro Presumido só é efetivamente devido por trimestre —
    este valor é apenas uma estimativa mês a mês para acompanhamento.
    """
    return _apurar([componente], cfg.LIMITE_ADICIONAL_MENSAL)


def consolidar_trimestre(ano: int, trimestre: int, meses: list[ComponenteMes]) -> ResultadoTrimestre:
    """
    Consolida os 3 meses de um trimestre-calendário e apura IRPJ e CSLL.

    `meses` deve conter exatamente os 3 ComponenteMes do trimestre, na ordem
    cronológica (ex.: abril, maio, junho para o 2º trimestre).
    """
    if len(meses) != 3:
        raise ValueError("É necessário informar os 3 meses do trimestre para consolidar.")

    irpj, csll = _apurar(meses, cfg.LIMITE_ADICIONAL_TRIMESTRE)

    parcelas_irpj = _montar_parcelas(irpj.valor_a_pagar)
    parcelas_csll = _montar_parcelas(csll.valor_a_pagar)

    return ResultadoTrimestre(
        ano=ano,
        trimestre=trimestre,
        competencias=[m.competencia for m in meses],
        irpj=irpj,
        csll=csll,
        parcelas_irpj=parcelas_irpj,
        parcelas_csll=parcelas_csll,
    )
