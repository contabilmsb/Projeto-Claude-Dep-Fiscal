"""
Geração do Excel de apuração da antecipação parcial do ICMS (sem
substituição tributária) sobre compras interestaduais na Bahia.
"""

import io

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill
from openpyxl.utils import get_column_letter

from .xml_parser import ItemAntecipacao
from .calculator import ResultadoAntecipacaoItem

HEADER_FILL = PatternFill("solid", fgColor="1B2A4A")
HEADER_FONT = Font(color="FFFFFF", bold=True, size=10)

COLUNAS = [
    ("Arquivo", 24), ("Chave NF-e", 26), ("Número NF", 10), ("Emissão", 12),
    ("CNPJ Emitente", 16), ("Emitente", 34), ("UF Origem", 8), ("UF Destino", 8),
    ("Regime", 16), ("CFOP", 8), ("NCM", 10), ("Item", 6), ("Descrição", 32),
    ("Valor Comercial", 14), ("Alíq. Interestadual", 12), ("Origem da Alíquota", 40),
    ("Categoria", 30), ("MVA Original", 12), ("MVA Ajustada", 12), ("Base de Cálculo", 14),
    ("Alíq. Interna BA", 12), ("Crédito de Origem", 14), ("Antecipação Devida", 16),
    ("Observações", 44),
]

COLS_MOEDA = {14, 20, 22, 23}
COLS_PERCENTUAL = {15, 18, 19, 21}


def _observacoes(item: ItemAntecipacao, res: ResultadoAntecipacaoItem) -> str:
    obs = []
    if not res.ajuste_aplicado:
        obs.append(
            "Alíquota interna não superior à interestadual — usada a MVA original sem ajuste (§15 do "
            "art. 289 do RICMS-BA)."
        )
    if item.uf_destino != "BA":
        obs.append(f"ATENÇÃO: UF de destino da nota é {item.uf_destino}, não BA")
    if item.uf_origem == item.uf_destino:
        obs.append("ATENÇÃO: operação interna (mesma UF de origem e destino) — antecipação não se aplica")
    if item.cfop_uso_consumo:
        obs.append(
            f"ATENÇÃO: CFOP {item.cfop} é típico de uso/consumo ou ativo imobilizado — pode ser caso de "
            "DIFAL, não de antecipação parcial (revenda)."
        )
    return "; ".join(obs)


def gerar_excel(
    linhas: list[tuple[ItemAntecipacao, ResultadoAntecipacaoItem]],
    categoria_label: str,
    avisos: list[str],
) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Antecipação ICMS"

    for col, (nome, largura) in enumerate(COLUNAS, start=1):
        cell = ws.cell(row=1, column=col, value=nome)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(col)].width = largura
    ws.freeze_panes = "A2"

    row = 2
    total_antecipacao = 0.0
    for item, res in linhas:
        valores = [
            item.arquivo, item.chave_nfe, item.numero_nf, (item.data_emissao or "")[:10],
            item.cnpj_emitente, item.nome_emitente, item.uf_origem, item.uf_destino,
            item.regime_emitente, item.cfop, item.ncm, item.n_item, item.descricao_produto,
            round(item.valor_comercial, 2), res.aliquota_interestadual, item.origem_aliquota,
            categoria_label, res.mva_original, res.mva_ajustada, round(res.base_calculo, 2),
            res.aliquota_interna, round(res.credito_origem, 2), round(res.antecipacao_devida, 2),
            _observacoes(item, res),
        ]
        for col, val in enumerate(valores, start=1):
            cell = ws.cell(row=row, column=col, value=val)
            if col in COLS_MOEDA:
                cell.number_format = "#,##0.00"
            if col in COLS_PERCENTUAL:
                cell.number_format = "0.00%"
        total_antecipacao += res.antecipacao_devida
        row += 1

    total_row = row
    ws.cell(row=total_row, column=1, value=f"TOTAL — {len(linhas)} item(ns)").font = Font(bold=True)
    ws.merge_cells(start_row=total_row, start_column=1, end_row=total_row, end_column=22)
    tot_cell = ws.cell(row=total_row, column=23, value=round(total_antecipacao, 2))
    tot_cell.font = Font(bold=True)
    tot_cell.number_format = "#,##0.00"

    if avisos:
        ws2 = wb.create_sheet("Avisos")
        ws2.cell(row=1, column=1, value="Avisos do processamento").font = Font(bold=True, size=12)
        for i, aviso in enumerate(avisos, start=3):
            ws2.cell(row=i, column=1, value=aviso)
        ws2.column_dimensions["A"].width = 110

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
