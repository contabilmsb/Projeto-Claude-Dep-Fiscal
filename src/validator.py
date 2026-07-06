"""
Validações cruzadas entre as planilhas fonte.
Identifica inconsistências antes da apuração.
"""

import pandas as pd
from dataclasses import dataclass, field


@dataclass
class Inconsistencia:
    tipo: str
    descricao: str
    nfs: list = field(default_factory=list)
    quantidade: int = 0
    valor_total: float = 0.0


def validar(dados: dict[str, pd.DataFrame]) -> list[Inconsistencia]:
    """
    Executa todas as validações e retorna lista de inconsistências encontradas.
    """
    alertas: list[Inconsistencia] = []

    recebidas  = dados["recebidas"]
    cofins_ret = dados["cofins_ret"]
    pis_ret    = dados["pis_ret"]
    csll_ret   = dados["csll_ret"]
    irrf       = dados["irrf"]
    juros      = dados["juros"]

    nfs_recebidas  = set(recebidas["nf"])
    nfs_cofins     = set(cofins_ret["nf"])
    nfs_pis        = set(pis_ret["nf"])
    nfs_csll       = set(csll_ret["nf"])
    nfs_irrf       = set(irrf["nf"])

    # ── 1. NFs com retenção de COFINS mas sem recebimento registrado ──────────
    sem_receb = nfs_cofins - nfs_recebidas
    if sem_receb:
        valor = cofins_ret[cofins_ret["nf"].isin(sem_receb)]["cofins_retido"].sum()
        alertas.append(Inconsistencia(
            tipo="COFINS_SEM_RECEBIMENTO",
            descricao="NFs com COFINS retido mas sem registro em Recebidas Clientes",
            nfs=sorted(sem_receb),
            quantidade=len(sem_receb),
            valor_total=valor,
        ))

    # ── 2. NFs com retenção de PIS mas sem recebimento registrado ─────────────
    sem_receb_pis = nfs_pis - nfs_recebidas
    if sem_receb_pis:
        valor = pis_ret[pis_ret["nf"].isin(sem_receb_pis)]["pis_retido"].sum()
        alertas.append(Inconsistencia(
            tipo="PIS_SEM_RECEBIMENTO",
            descricao="NFs com PIS retido mas sem registro em Recebidas Clientes",
            nfs=sorted(sem_receb_pis),
            quantidade=len(sem_receb_pis),
            valor_total=valor,
        ))

    # ── 3. Proporção PIS/COFINS divergente (esperado: 0.65/3 ≈ 21,67%) ────────
    nfs_ambos = nfs_cofins & nfs_pis
    if nfs_ambos:
        merged = cofins_ret.merge(pis_ret, on="nf")
        merged = merged[merged["nf"].isin(nfs_ambos)].copy()
        merged["proporcao"] = merged["pis_retido"] / merged["cofins_retido"].replace(0, float("nan"))
        esperado = 0.0065 / 0.03  # ≈ 0.2167
        tolerancia = 0.01         # 1% de margem
        divergentes = merged[
            (merged["proporcao"] - esperado).abs() > tolerancia
        ]
        if not divergentes.empty:
            nfs_div = sorted(divergentes["nf"].tolist())
            alertas.append(Inconsistencia(
                tipo="PROPORCAO_PIS_COFINS_DIVERGENTE",
                descricao=(
                    f"NFs com proporção PIS/COFINS diferente de {esperado:.4f} "
                    f"(esperado para alíq. 0,65%/3,00%) — verifique se há retenção correta"
                ),
                nfs=nfs_div,
                quantidade=len(nfs_div),
            ))

    # ── 4. NFs com CSLL retida mas sem COFINS/PIS (possível omissão) ──────────
    csll_sem_cofins = nfs_csll - nfs_cofins
    if csll_sem_cofins:
        valor = csll_ret[csll_ret["nf"].isin(csll_sem_cofins)]["csll_retido"].sum()
        alertas.append(Inconsistencia(
            tipo="CSLL_SEM_COFINS",
            descricao="NFs com CSLL retida mas sem COFINS retido registrado",
            nfs=sorted(csll_sem_cofins),
            quantidade=len(csll_sem_cofins),
            valor_total=valor,
        ))

    # ── 5. Duplicidades em Recebidas ──────────────────────────────────────────
    duplicados = recebidas[recebidas.duplicated(subset=["nf"], keep=False)]
    if not duplicados.empty:
        alertas.append(Inconsistencia(
            tipo="DUPLICIDADE_RECEBIDAS",
            descricao="NFs com mais de um lançamento em Recebidas Clientes "
                      "(valores foram somados — verifique se correto)",
            nfs=sorted(duplicados["nf"].unique().tolist()),
            quantidade=duplicados["nf"].nunique(),
        ))

    # ── 6. NFs com juros mas sem recebimento ──────────────────────────────────
    nfs_juros = set(juros["nf"])
    juros_sem_receb = nfs_juros - nfs_recebidas
    if juros_sem_receb:
        valor = juros[juros["nf"].isin(juros_sem_receb)]["juros"].sum()
        alertas.append(Inconsistencia(
            tipo="JUROS_SEM_RECEBIMENTO",
            descricao="NFs com juros/multas mas sem recebimento principal registrado",
            nfs=sorted(juros_sem_receb),
            quantidade=len(juros_sem_receb),
            valor_total=valor,
        ))

    return alertas


def relatorio_validacao(alertas: list[Inconsistencia]) -> str:
    """Formata o relatório de validação em texto."""
    if not alertas:
        return "✓ Nenhuma inconsistência encontrada."

    linhas = [f"{'='*60}", f"  RELATÓRIO DE VALIDAÇÃO — {len(alertas)} alerta(s)", f"{'='*60}"]
    for i, a in enumerate(alertas, 1):
        linhas.append(f"\n[{i}] {a.tipo}")
        linhas.append(f"    {a.descricao}")
        linhas.append(f"    Quantidade: {a.quantidade} NF(s)")
        if a.valor_total:
            linhas.append(f"    Valor total: R$ {a.valor_total:,.2f}")
        if a.nfs:
            nfs_str = ", ".join(a.nfs[:10])
            if len(a.nfs) > 10:
                nfs_str += f" ... (+{len(a.nfs)-10} outras)"
            linhas.append(f"    NFs: {nfs_str}")
    return "\n".join(linhas)
