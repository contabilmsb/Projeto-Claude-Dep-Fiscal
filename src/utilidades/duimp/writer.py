"""
Geração do Excel da DUIMP: aba "Itens" (uma linha por mercadoria, com os
valores rateados), aba "Resumo" (dados do processo) e aba "Avisos" quando
algo relevante precisa de atenção.
"""

import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill("solid", fgColor="1B2A4A")
HEADER_FONT = Font(color="FFFFFF", bold=True, size=10)
RATEIO_FILL = PatternFill("solid", fgColor="FFF3CD")

COLUNAS = [
    ("item", "Item", 8, None, False),
    ("part_number", "Código do Produto", 18, None, False),
    ("descricao_complementar", "Descrição do Produto", 55, None, False),
    ("ncm", "NCM", 16, None, False),
    ("quantidade", "Quantidade", 12, "#,##0.00", False),
    ("numero_lote", "Número do Lote", 16, None, False),
    ("data_fabricacao", "Data de Fabricação", 14, None, False),
    ("fabricante_legal", "Fabricante", 30, None, False),
    ("pais_origem", "País de Origem", 20, None, False),
    ("fornecedor", "Fornecedor (Exportador)", 32, None, False),
    ("pais_aquisicao", "País de Aquisição", 20, None, False),
    ("moeda_negociada", "Moeda Negociada", 16, None, False),
    ("valor_unitario", "Valor Unitário", 16, "#,##0.0000", False),
    ("valor_total_venda", "Valor Total (moeda)", 16, "#,##0.00", False),
    ("peso_liquido_kg", "Peso Líquido (kg)", 16, "#,##0.00000", False),
    ("peso_bruto_rateado_kg", "Peso Bruto Rateado (kg)", 18, "#,##0.00000", True),
    ("valor_aduaneiro_rateado_brl", "Valor Aduaneiro Rateado (R$)", 20, "#,##0.00", True),
    ("ii_regime", "II - Regime", 20, None, False),
    ("ii_rateado_brl", "II Rateado (R$)", 16, "#,##0.00", True),
    ("ipi_regime", "IPI - Regime", 20, None, False),
    ("ipi_rateado_brl", "IPI Rateado (R$)", 16, "#,##0.00", True),
    ("pis_regime", "PIS - Regime", 16, None, False),
    ("pis_rateado_brl", "PIS Rateado (R$)", 16, "#,##0.00", True),
    ("cofins_regime", "COFINS - Regime", 16, None, False),
    ("cofins_rateado_brl", "COFINS Rateado (R$)", 18, "#,##0.00", True),
    ("cclasstrib", "Class. Tributária (cClassTrib)", 45, None, False),
    ("finalidade_importacao", "Finalidade da Importação", 22, None, False),
    ("cnpj_destino_final", "CNPJ Destino Final", 18, None, False),
    ("dispositivo_recondicionado", "Dispositivo Recondicionado", 16, None, False),
    ("numero_snvs", "Registro SNVS", 16, None, False),
]
COLUNAS_TOTAL = [
    "quantidade", "peso_liquido_kg", "peso_bruto_rateado_kg", "valor_total_venda",
    "valor_aduaneiro_rateado_brl", "ii_rateado_brl", "ipi_rateado_brl",
    "pis_rateado_brl", "cofins_rateado_brl",
]


def _gerar_aba_itens(ws, itens: list[dict]) -> None:
    for col_idx, (_, titulo, largura, _, rateado) in enumerate(COLUNAS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=titulo)
        cell.font = HEADER_FONT
        cell.fill = RATEIO_FILL if rateado else HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(col_idx)].width = largura
    ws.freeze_panes = "A2"

    row_idx = 2
    for item in itens:
        for col_idx, (chave, _, _, formato, _) in enumerate(COLUNAS, start=1):
            valor = item.get(chave)
            cell = ws.cell(row=row_idx, column=col_idx, value=valor)
            if formato:
                cell.number_format = formato
        row_idx += 1

    total_row = row_idx
    idx_por_chave = {chave: i + 1 for i, (chave, *_r) in enumerate(COLUNAS)}
    ws.cell(row=total_row, column=1, value=f"TOTAL — {len(itens)} item(ns)").font = Font(bold=True)
    ws.merge_cells(start_row=total_row, start_column=1, end_row=total_row, end_column=3)
    for chave in COLUNAS_TOTAL:
        col_idx = idx_por_chave[chave]
        total = sum(item.get(chave) or 0 for item in itens)
        tot_cell = ws.cell(row=total_row, column=col_idx, value=round(total, 5))
        tot_cell.font = Font(bold=True)
        formato = next(f for c, _, _, f, _ in COLUNAS if c == chave)
        if formato:
            tot_cell.number_format = formato


def _gerar_aba_resumo(ws, cabecalho: dict, qtd_itens: int) -> None:
    linhas = [
        ("Número da DUIMP", cabecalho.get("duimp_numero")),
        ("Versão", cabecalho.get("versao")),
        ("Importador — CNPJ", cabecalho.get("importador_cnpj")),
        ("Importador — Nome", cabecalho.get("importador_nome")),
        ("Processo Virtua Comex", cabecalho.get("processo_virtua")),
        ("Processo Biomedical", cabecalho.get("processo_biomedical")),
        ("Exportador / Fabricante", cabecalho.get("exportador_fabricante")),
        ("Fatura Comercial", cabecalho.get("fatura_comercial")),
        ("Data de Embarque", cabecalho.get("data_embarque")),
        ("Data de Chegada", cabecalho.get("data_chegada")),
        ("Câmbio (Taxa Dólar)", cabecalho.get("taxa_dolar")),
        ("Taxa Siscomex (R$)", cabecalho.get("taxa_siscomex")),
        ("FOB (USD)", cabecalho.get("fob_usd")),
        ("FOB (R$)", cabecalho.get("fob_brl")),
        ("Frete Internacional (USD)", cabecalho.get("frete_usd")),
        ("Frete Internacional (R$)", cabecalho.get("frete_brl")),
        ("Seguro (USD)", cabecalho.get("seguro_usd")),
        ("Seguro (R$)", cabecalho.get("seguro_brl")),
        ("Valor Aduaneiro (USD)", cabecalho.get("valor_aduaneiro_usd")),
        ("Valor Aduaneiro (R$)", cabecalho.get("valor_aduaneiro_brl")),
        ("ICMS Total (R$)", cabecalho.get("icms_total")),
        ("Despesas Aduaneiras (R$)", cabecalho.get("despesas_aduaneiras")),
        ("Peso Bruto Total (kg)", cabecalho.get("peso_bruto_total_kg")),
        ("Peso Líquido Total (kg)", cabecalho.get("peso_liquido_total_kg")),
        ("Quantidade de Itens", qtd_itens),
    ]
    for a in cabecalho.get("adicoes") or []:
        linhas.append((
            f"Adição {a['numero']} — NCM {a['ncm']}",
            f"II R$ {a.get('ii_valor') or 0:.2f} | IPI R$ {a.get('ipi_valor') or 0:.2f} | "
            f"Base PIS/COFINS R$ {a.get('base_pis_cofins') or 0:.2f} | "
            f"PIS R$ {a.get('pis_valor') or 0:.2f} | COFINS R$ {a.get('cofins_valor') or 0:.2f}",
        ))

    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 90
    for row_idx, (campo, valor) in enumerate(linhas, start=1):
        c1 = ws.cell(row=row_idx, column=1, value=campo)
        c1.font = Font(bold=True)
        ws.cell(row=row_idx, column=2, value=valor)

    nota_row = len(linhas) + 2
    ws.cell(row=nota_row, column=1, value="Metodologia de rateio").font = Font(bold=True, size=12)
    nota = (
        "A DUIMP não traz peso bruto nem tributos (II/IPI/PIS/COFINS) por item — só o total do "
        "processo (peso bruto) e o total por adição do Siscomex (tributos). Nesta planilha, essas "
        "colunas (destacadas em amarelo na aba Itens) foram RATEADAS: o peso bruto proporcionalmente "
        "à participação de cada item no peso líquido total, e o valor aduaneiro e os tributos "
        "proporcionalmente à participação de cada item no valor total na condição de venda. São "
        "estimativas, não o valor exato apurado pela Receita Federal por item."
    )
    ws.cell(row=nota_row + 1, column=1, value=nota).alignment = Alignment(wrap_text=True)
    ws.merge_cells(start_row=nota_row + 1, start_column=1, end_row=nota_row + 1, end_column=2)
    ws.row_dimensions[nota_row + 1].height = 60


def gerar_excel(cabecalho: dict, itens: list[dict], avisos: list[str]) -> bytes:
    wb = Workbook()
    ws_itens = wb.active
    ws_itens.title = "Itens"
    _gerar_aba_itens(ws_itens, itens)

    ws_resumo = wb.create_sheet("Resumo")
    _gerar_aba_resumo(ws_resumo, cabecalho, len(itens))

    if avisos:
        ws_avisos = wb.create_sheet("Avisos")
        ws_avisos.cell(row=1, column=1, value="Avisos do processamento").font = Font(bold=True, size=12)
        for i, aviso in enumerate(avisos, start=3):
            ws_avisos.cell(row=i, column=1, value=aviso)
        ws_avisos.column_dimensions["A"].width = 110

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
