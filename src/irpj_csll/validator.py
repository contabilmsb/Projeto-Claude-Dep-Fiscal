"""
Validações do módulo IRPJ/CSLL.
"""

from dataclasses import dataclass

from .calculator import meses_do_trimestre


@dataclass
class Alerta:
    tipo: str
    descricao: str


def validar_trimestre_completo(competencias_presentes: list[str], trimestre: int, ano: int) -> list[Alerta]:
    """Verifica se os 3 meses do trimestre já foram processados neste módulo."""
    esperadas = {f"{m:02d}/{ano}" for m in meses_do_trimestre(trimestre)}
    faltantes = esperadas - set(competencias_presentes)
    if not faltantes:
        return []
    return [Alerta(
        tipo="TRIMESTRE_INCOMPLETO",
        descricao=(
            f"Faltam as competências {', '.join(sorted(faltantes))} para fechar "
            f"o {trimestre}º trimestre de {ano}."
        ),
    )]


def validar_selic_incompleta(parcelas: list) -> list[Alerta]:
    """Sinaliza parcelas cuja taxa SELIC não pôde ser obtida integralmente via API do BCB."""
    incompletas = [p for p in parcelas if not p.selic_completa]
    if not incompletas:
        return []
    numeros = ", ".join(str(p.numero) for p in incompletas)
    return [Alerta(
        tipo="SELIC_INDISPONIVEL",
        descricao=(
            f"Não foi possível obter a taxa SELIC de todas as parcelas ({numeros}) "
            "via API do Banco Central. Informe a taxa manualmente para maior precisão."
        ),
    )]
