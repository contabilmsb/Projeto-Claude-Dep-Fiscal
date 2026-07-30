"""
Taxa SELIC acumulada para correção das 2ª e 3ª parcelas do IRPJ/CSLL
(Lei 9.430/1996, art. 5º §§2º-3º):
  - Parcela 1: sem acréscimo, vence no último dia útil do mês seguinte ao
    encerramento do trimestre.
  - Parcela 2: SELIC acumulada do mês do vencimento da parcela 1 até o mês
    anterior ao pagamento, mais 1% no mês do pagamento.
  - Parcela 3: idem, acumulando mais um mês de SELIC.

Fonte: API pública do Banco Central (SGS), série 4390 — "Taxa de juros -
Selic acumulada no mês (%)".
"""

import httpx

_SERIE_SELIC_MENSAL = 4390
_cache: dict[tuple[int, int], float] = {}


def _mes_seguinte(ano: int, mes: int, n: int = 1) -> tuple[int, int]:
    total = (ano * 12 + (mes - 1)) + n
    return total // 12, total % 12 + 1


def _selic_mensal(ano: int, mes: int) -> float | None:
    """Retorna a taxa SELIC do mês (decimal, ex.: 0.0123 = 1,23%) ou None se indisponível."""
    key = (ano, mes)
    if key in _cache:
        return _cache[key]

    data_ini = f"01/{mes:02d}/{ano}"
    ultimo_dia = 28
    for d in (31, 30, 29, 28):
        try:
            import datetime
            datetime.date(ano, mes, d)
            ultimo_dia = d
            break
        except ValueError:
            continue
    data_fim = f"{ultimo_dia:02d}/{mes:02d}/{ano}"

    url = (
        f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{_SERIE_SELIC_MENSAL}/dados"
        f"?formato=json&dataInicial={data_ini}&dataFinal={data_fim}"
    )
    try:
        resp = httpx.get(url, timeout=8.0)
        resp.raise_for_status()
        dados = resp.json()
        if not dados:
            return None
        taxa = float(dados[-1]["valor"]) / 100.0
        _cache[key] = taxa
        return taxa
    except Exception:
        return None


def acrescimo_parcela(numero_parcela: int, ano_fim_trimestre: int, mes_fim_trimestre: int,
                       overrides: dict[int, float] | None = None) -> tuple[float, bool]:
    """
    Retorna (percentual_acrescimo, completo) para a parcela informada.

    `completo=False` indica que uma ou mais taxas mensais não puderam ser
    obtidas da API do BCB — o chamador deve sinalizar isso na UI e permitir
    informar `overrides` (dict mês-sequencial → taxa decimal) manualmente.
    """
    if numero_parcela <= 1:
        return 0.0, True

    overrides = overrides or {}
    ano, mes = _mes_seguinte(ano_fim_trimestre, mes_fim_trimestre, 1)  # mês de venc. da parcela 1
    acumulado = 0.0
    completo = True
    for i in range(numero_parcela - 1):
        seq = i
        if seq in overrides:
            taxa = overrides[seq]
        else:
            taxa = _selic_mensal(ano, mes)
            if taxa is None:
                completo = False
                taxa = 0.0
        acumulado += taxa
        ano, mes = _mes_seguinte(ano, mes, 1)

    return acumulado + 0.01, completo
