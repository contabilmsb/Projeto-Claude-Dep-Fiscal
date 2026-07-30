"""
Configurações da apuração IRPJ/CSLL — regime de Lucro Presumido, base caixa.

Os percentuais de presunção de "Revendas" (8,8% IRPJ / 13,2% CSLL) foram
confirmados com a contabilidade como um ajuste intencional sobre os
percentuais padrão da Lei 9.249/1995 (8% / 12% para comércio/revenda de
mercadorias) — não alterar sem validação da contabilidade.
"""

# ─── Percentuais de presunção (regime de Lucro Presumido) ─────────────────────
IRPJ_REVENDA_RATE = 0.088   # Revenda de mercadorias — ajuste intencional (padrão legal: 8%)
CSLL_REVENDA_RATE = 0.132   # Revenda de mercadorias — ajuste intencional (padrão legal: 12%)
IRPJ_SERVICOS_RATE = 0.32   # Serviços em geral — Lei 9.249/95 art.15 §1º III
CSLL_SERVICOS_RATE = 0.32   # Serviços em geral — Lei 9.249/95 art.20
OUTRAS_RECEITAS_RATE = 1.0  # Demais receitas/ganhos — incluídas a 100% (Lei 9.430/96 art.25, II)

# ─── Alíquotas finais ──────────────────────────────────────────────────────────
IRPJ_RATE = 0.15
IRPJ_ADICIONAL_RATE = 0.10
LIMITE_ADICIONAL_MENSAL = 20_000.0
LIMITE_ADICIONAL_TRIMESTRE = LIMITE_ADICIONAL_MENSAL * 3   # R$ 60.000,00
CSLL_RATE = 0.09

# ─── DARF ──────────────────────────────────────────────────────────────────────
DARF_COD_IRPJ = "2089"
DARF_COD_CSLL = "2372"

# ─── Parcelamento trimestral ───────────────────────────────────────────────────
N_PARCELAS = 3
VALOR_MINIMO_PARCELA = 1_000.0   # Lei 9.430/96 art.5º §2º — parcela mínima R$1.000
