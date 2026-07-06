"""
Configurações centralizadas da ferramenta de apuração PIS/COFINS.
Ajuste os caminhos e alíquotas aqui quando necessário.
"""

from pathlib import Path

# ─── Diretório base das planilhas fonte ────────────────────────────────────────
SOURCE_DIR = Path(
    r"C:\Users\patricio.oliveira\OneDrive - BIOMEDICAL S A"
    r"\Documentos Fiscais MSB\Projeto Claude\Apuração Pis Cofins"
)

OUTPUT_DIR = Path(r"C:\Projeto Claude Dep Fiscal\output")

# ─── Arquivos fonte (atualize os nomes para cada competência) ─────────────────
SOURCE_FILES = {
    "template":   SOURCE_DIR / "Apuração PIS COFINS.xlsx",
    "recebidas":  SOURCE_DIR / "Recebidas Clientes 05.2026.xlsx",
    "cofins_ret": SOURCE_DIR / "COFINS Retido 05.2026.xlsx",
    "pis_ret":    SOURCE_DIR / "PIS Retido  05.2026.xlsx",
    "csll_ret":   SOURCE_DIR / "CSLL Retido 05.2026.xlsx",
    "irrf":       SOURCE_DIR / "IRRF 05.2026.xlsx",
    "juros":      SOURCE_DIR / "JUROS RECEBIDOS.xlsx",
    "vendas":     SOURCE_DIR / "VENDAS.xlsx",
}

# ─── Competência apurada ───────────────────────────────────────────────────────
COMPETENCIA = "05/2026"

# Serial Excel do mês de apuração (1º dia do mês seguinte = último dia do mês)
# 46170 corresponde a 31/05/2026 — é o valor que aparece como cabeçalho de coluna
# na planilha modelo. Atualize para cada competência.
COMPETENCIA_SERIAL = 46170

# ─── Estornos: NFs a excluir do cálculo ──────────────────────────────────────
# Adicione aqui os números de NF (9 dígitos, com zeros à esquerda) que devem
# ser estornados da apuração do período. Os valores de recebimento e retenções
# dessas NFs serão removidos de todas as fontes antes do cálculo.
ESTORNOS: list[str] = [
    "000019518",   # W MEDICAL S.A — estorno solicitado em 29/06/2026
]

# ─── Alíquotas (regime cumulativo) ────────────────────────────────────────────
COFINS_RATE = 0.03    # 3,00%
PIS_RATE    = 0.0065  # 0,65%

# ─── Rótulos das linhas no template (coluna F da aba) ─────────────────────────
# Usados para localizar células dinamicamente — tolerante a maiúsculas/espaços.
LABELS = {
    # COFINS
    "receita_revenda":   "receita c/ revenda",
    "descontos":         "descontos concedidos",
    "outras_receitas":   "demais receitas",
    "total_receitas":    "total receitas",
    "total_exclusoes":   "total exclus",          # prefixo p/ capturar acento
    "base_cofins":       "base c",                # "base cálculo cofins"
    "vr_cofins":         "vr apurado cofins",
    "cofins_retida":     "cofins retida",
    "total_deducoes":    "total dedu",
    "cofins_pagar":      "cofins a pagar",
    # PIS (mesmos labels, aba diferente)
    "vr_pis":            "vr apurado pis",
    "pis_retida":        "pis retida",
    "pis_pagar":         "pis a pagar",
}
