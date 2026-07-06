"""
Ferramenta de Apuração PIS/COFINS — MSB Medical System do Brasil
Regime Cumulativo (Lei 9.718/98)

Uso:
    python main.py

    # Para uma competência diferente, edite config.py:
    #   COMPETENCIA, COMPETENCIA_SERIAL, SOURCE_FILES
"""

import sys
import os
from pathlib import Path
from datetime import datetime

# Força UTF-8 no terminal Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Garante que o diretório raiz está no path
sys.path.insert(0, str(Path(__file__).parent))

from src.config import SOURCE_FILES, OUTPUT_DIR, COMPETENCIA, COMPETENCIA_SERIAL, COFINS_RATE, PIS_RATE, ESTORNOS

# Extrai mês/ano da competência "MM/YYYY"
_mes, _ano = [int(x) for x in COMPETENCIA.split("/")]
from src.readers import load_all
from src.calculator import calcular
from src.validator import validar, relatorio_validacao
from src.writer import atualizar_template


def _fmt(valor: float) -> str:
    return f"R$ {valor:>15,.2f}"


def main():
    print("=" * 60)
    print(f"  APURAÇÃO PIS/COFINS — COMPETÊNCIA {COMPETENCIA}")
    print(f"  Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print("=" * 60)

    # ── 1. Verificar arquivos ─────────────────────────────────────────────────
    print("\n[1/5] Verificando arquivos fonte...")
    missing = [k for k, v in SOURCE_FILES.items() if not Path(v).exists()]
    if missing:
        print(f"\n  ERRO: Arquivos não encontrados: {missing}")
        sys.exit(1)
    print("  ✓ Todos os arquivos encontrados.")

    # ── 2. Carregar dados ─────────────────────────────────────────────────────
    if ESTORNOS:
        print(f"\n  Estornos ativos: {', '.join(ESTORNOS)}")

    print("\n[2/5] Carregando planilhas...")
    try:
        dados = load_all(SOURCE_FILES, estornos=ESTORNOS)
        print(f"  ✓ Recebidas Clientes:  {len(dados['recebidas']):>4} registros")
        print(f"  ✓ COFINS Retido:       {len(dados['cofins_ret']):>4} registros")
        print(f"  ✓ PIS Retido:          {len(dados['pis_ret']):>4} registros")
        print(f"  ✓ CSLL Retida:         {len(dados['csll_ret']):>4} registros")
        print(f"  ✓ IRRF:                {len(dados['irrf']):>4} registros")
        print(f"  ✓ Juros Recebidos:     {len(dados['juros']):>4} registros")
        print(f"  ✓ Vendas:              {len(dados['vendas']):>4} registros")
    except Exception as e:
        print(f"\n  ERRO ao carregar planilhas: {e}")
        raise

    # ── 3. Validação ──────────────────────────────────────────────────────────
    print("\n[3/5] Executando validações...")
    alertas = validar(dados)
    if alertas:
        print(f"  ⚠ {len(alertas)} inconsistência(s) encontrada(s) — veja aba 'Validação'")
    else:
        print("  ✓ Nenhuma inconsistência encontrada.")

    # ── 4. Cálculo ────────────────────────────────────────────────────────────
    print("\n[4/5] Calculando apuração...")
    resultado = calcular(dados, COMPETENCIA, COFINS_RATE, PIS_RATE)
    c = resultado.cofins
    p = resultado.pis

    print(f"\n  {'─'*45}")
    print(f"  {'DEMONSTRATIVO DE APURAÇÃO':^45}")
    print(f"  {'─'*45}")
    print(f"  Total recebido de clientes : {_fmt(resultado.total_recebido)}")
    print(f"  (+) COFINS retido          : {_fmt(c.retencao_fonte)}")
    print(f"  (+) PIS retido             : {_fmt(p.retencao_fonte)}")
    print(f"  (+) CSLL retida            : {_fmt(resultado.csll_retida)}")
    print(f"  (+) IRRF retido            : {_fmt(resultado.irrf_retido)}")
    print(f"  (-) Juros/multas recebidos : {_fmt(resultado.total_juros)}")
    print(f"  {'─'*45}")
    print(f"  BASE LÍQUIDA (PIS/COFINS)  : {_fmt(c.base_calculo)}")
    print(f"  {'─'*45}")
    print(f"  COFINS apurado ({c.aliquota*100:.2f}%)   : {_fmt(c.valor_apurado)}")
    print(f"  COFINS retido na fonte     : {_fmt(c.retencao_fonte)}")
    print(f"  COFINS A RECOLHER          : {_fmt(c.valor_a_pagar)}")
    print(f"  {'─'*45}")
    print(f"  PIS apurado ({p.aliquota*100:.4f}%)  : {_fmt(p.valor_apurado)}")
    print(f"  PIS retido na fonte        : {_fmt(p.retencao_fonte)}")
    print(f"  PIS A RECOLHER             : {_fmt(p.valor_a_pagar)}")
    print(f"  {'─'*45}")
    print(f"  CSLL retida (informativo)  : {_fmt(resultado.csll_retida)}")
    print(f"  IRRF retido (informativo)  : {_fmt(resultado.irrf_retido)}")
    print(f"  {'─'*45}")

    # ── 5. Geração da planilha ────────────────────────────────────────────────
    print("\n[5/5] Gerando planilha de saída...")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUT_DIR / f"Apuração PIS COFINS {COMPETENCIA.replace('/', '.')} {timestamp}.xlsx"

    try:
        output_path, log = atualizar_template(
            template_path=SOURCE_FILES["template"],
            output_path=output_path,
            resultado=resultado,
            dados=dados,
            target_month=_mes,
            target_year=_ano,
            alertas=alertas,
        )
        print(f"  Coluna COFINS inserida: {log.get('cofins_col')} | PIS: {log.get('pis_col')}")
        print(f"\n  ✓ Planilha salva em:\n    {output_path}")
    except Exception as e:
        print(f"\n  ERRO ao gerar planilha: {e}")
        raise

    # Relatório de validação
    if alertas:
        print(f"\n{relatorio_validacao(alertas)}")

    print("\n" + "=" * 60)
    print("  APURAÇÃO CONCLUÍDA")
    print("=" * 60)


if __name__ == "__main__":
    main()
