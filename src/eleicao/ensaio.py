"""Ensaio: reproduz um 2º turno já conhecido e mede o erro da projeção a cada ponto da apuração.

A ordem `real` usa a hora em que cada seção entrou na totalização. As outras ordens testam o modelo
contra chegadas que ele nunca viu: `aleatoria` sorteia a ordem das seções, `invertida` começa pelas
seções que chegaram por último.
"""

import json
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from eleicao.base.abertos import CHAVE
from eleicao.config import BASES, DADOS, ELEICOES
from eleicao.modelo import Modelo, Parametros
from eleicao.saida import Saida, ler_validacao
from eleicao.tipos import Apuracao, Base, Projecao

PONTOS_PCT = (0.25, 0.5, 1, 1.5, 2, 3, 4, 5, 7, 10, 15, 20, 30, 40, 50, 60, 70, 80, 90, 95, 99)
PONTOS_EXEMPLO = (0.1, 0.25, 0.5, 1, 1.5, 2, 3, 4, 5, 7, 10, 12.5, 15, 17.5, 20, 25, 30, 35, 40, 45, 50)
ORDENS = ("real", "aleatoria", "invertida")


def cenario_alinhado(base: Base, ano: int) -> pl.DataFrame:
    cen = pl.read_parquet(BASES / str(ano) / "cenario.parquet")
    alinhado = base.secoes.select(CHAVE).join(cen, on=CHAVE, how="left", maintain_order="left")
    if alinhado["esq"].null_count():
        raise ValueError("seções da base sem resultado no cenário")
    return alinhado


def apuracao_ate(base: Base, cen: pl.DataFrame, posto: np.ndarray, limite: int, momento: datetime) -> Apuracao:
    """Apuracao com as seções de `posto` < `limite` totalizadas (posto = posição na ordem de chegada)."""
    tot = posto < limite
    mi, nm = base.mun_idx, base.n_municipios

    def soma(c: str) -> np.ndarray:
        return np.bincount(mi, cen[c].to_numpy() * tot, nm).astype(np.int64)

    return Apuracao(
        momento=momento, totalizada=tot, esq=soma("esq"), dir=soma("dir"), brancos=soma("brancos"),
        nulos=soma("nulos"), comparecimento=soma("comparecimento"), aptos=soma("aptos"),
        secoes=np.bincount(mi, tot, nm).astype(np.int64),
    )


def postos(cen: pl.DataFrame, ordem: str, semente: int = 1) -> np.ndarray:
    n = cen.height
    rng = np.random.default_rng(semente)
    chave = cen["hora"].to_numpy().astype("datetime64[s]").astype(np.int64).astype(float)
    if ordem == "aleatoria":
        chave = rng.random(n)
    elif ordem == "invertida":
        chave = -chave
    sequencia = np.lexsort((rng.random(n), chave))
    posto = np.empty(n, dtype=np.int64)
    posto[sequencia] = np.arange(n)
    return posto


def rodar(ano: int, ordem: str, parametros: Parametros = Parametros(), base: Base | None = None) -> pl.DataFrame:
    base = base or Base.ler(BASES / str(ano))
    cen = cenario_alinhado(base, ano)
    final = 100 * cen["esq"].sum() / (cen["esq"].sum() + cen["dir"].sum())
    final_uf = (
        cen.with_columns(pl.Series("uf", base.secoes["uf"])).group_by("uf")
        .agg((100 * pl.col("esq").sum() / (pl.col("esq").sum() + pl.col("dir").sum())).alias("final"))
    )
    final_uf = dict(zip(final_uf["uf"], final_uf["final"]))
    modelo = Modelo(base, parametros)
    posto = postos(cen, ordem)
    inicio = datetime(ano, 10, 30, 17)
    linhas = []
    for pct in PONTOS_PCT:
        limite = int(np.ceil(cen.height * pct / 100))
        proj = modelo.projetar(apuracao_ate(base, cen, posto, limite, inicio + timedelta(minutes=pct)))
        b = proj.brasil
        f = b.projecao
        abertas = {u: r for u, r in proj.ufs.items() if r.projecao and r.pct_secoes < 100}
        erro_uf = [abs(r.projecao.centro - final_uf[u]) for u, r in abertas.items()]
        cobre_uf = [r.projecao.baixo - 0.005 <= final_uf[u] <= r.projecao.alto + 0.005 for u, r in abertas.items()]
        linhas.append({
            "ordem": ordem, "pct_secoes": b.pct_secoes, "apurado": b.apurado, "final": final,
            "centro": f and f.centro, "baixo": f and f.baixo, "alto": f and f.alto, "chance": f and f.chance,
            "erro_uf_medio": float(np.mean(erro_uf)) if erro_uf else None,
            "cobertura_uf": float(np.mean(cobre_uf)) if cobre_uf else None,
        })
    return pl.DataFrame(linhas).with_columns(
        (pl.col("centro") - pl.col("final")).alias("erro"),
        ((pl.col("baixo") <= pl.col("final")) & (pl.col("final") <= pl.col("alto"))).alias("cobre"),
        pl.when(pl.col("final") > 50).then(100 - pl.col("chance")).otherwise(pl.col("chance")).alias("chance_perdedor"),
    )


def resumo(df: pl.DataFrame, desde_pct: float = 5.0) -> dict:
    d = df.filter(pl.col("pct_secoes") >= desde_pct)
    return {
        "desde_pct": desde_pct,
        "erro_medio_pp": round(float(d["erro"].abs().mean()), 3),
        "erro_max_pp": round(float(d["erro"].abs().max()), 3),
        "cobertura_faixa": round(float(d["cobre"].mean()), 3),
        "erro_medio_apurado_pp": round(float((d["apurado"] - d["final"]).abs().mean()), 3),
        "chance_max_de_quem_perdeu": round(float(df.filter(pl.col("pct_secoes") >= 1)["chance_perdedor"].max()), 1),
    }


def ensaiar(ano: int) -> None:
    pl.Config.set_tbl_rows(40)
    pl.Config.set_tbl_cols(20)
    pl.Config.set_tbl_width_chars(200)
    base = Base.ler(BASES / str(ano))
    pasta = DADOS / "ensaio"
    pasta.mkdir(parents=True, exist_ok=True)
    tabelas = []
    for ordem in ORDENS:
        df = rodar(ano, ordem, base=base)
        tabelas.append(df)
        print(f"\n## ordem {ordem}: final {df['final'][0]:.2f}%")
        print(df.select(
            pl.col("pct_secoes").round(2), pl.col("apurado").round(2), pl.col("centro").round(2),
            pl.col("baixo").round(2), pl.col("alto").round(2), pl.col("erro").round(3), "cobre",
            pl.col("erro_uf_medio").round(2), pl.col("cobertura_uf").round(2),
        ))
        print(resumo(df))
    tudo = pl.concat(tabelas)
    tudo.write_parquet(pasta / f"{ano}.parquet")
    real = tudo.filter(pl.col("ordem") == "real")
    doc = {"eleicao": f"2º turno de {ano}", **resumo(real), "por_ordem": {o: resumo(tudo.filter(pl.col("ordem") == o)) for o in ORDENS}}
    (pasta / f"{ano}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(doc, ensure_ascii=False))


def gravar_exemplo(
    base: Base, cen: pl.DataFrame, destino: Path, momento: Callable[[np.datetime64], datetime]
) -> Iterator[tuple[float, datetime, Projecao]]:
    """Grava em `destino` a apuração de 2026 de `cen` até `PONTOS_EXEMPLO`, na ordem real de chegada, marcada como exemplo.

    Cada ponto passa pelo mesmo `Modelo` e pela mesma `Saida` do acompanhamento ao vivo. `momento` converte a hora
    da última seção do ponto no instante gravado. Devolve cada ponto à medida que sai, para o chamador imprimir.
    """
    posto = postos(cen, "real")
    horas = np.sort(cen["hora"].drop_nulls().to_numpy())
    modelo = Modelo(base)
    destino.unlink(missing_ok=True)
    saida = Saida(ELEICOES[2026], base, destino, ler_validacao(DADOS / "ensaio"), exemplo=True)
    for pct in PONTOS_EXEMPLO:
        limite = int(np.ceil(cen.height * pct / 100))
        instante = momento(horas[limite - 1])
        proj = modelo.projetar(apuracao_ate(base, cen, posto, limite, instante))
        saida.registrar(proj, "apurando", instante)
        yield pct, instante, proj


def cenario_sintetico(base: Base, swing: float, semente: int = 0) -> pl.DataFrame:
    """Um 2º turno inventado sobre a Base: cada seção recebe a fração da esquerda do 1º turno mais
    `swing` (logit) e um ruído por município e por seção; os demais candidatos se dividem pela mesma
    regra; a hora de chegada é a do 1º turno com um atraso sorteado. Serve aos testes e ao ensaio
    ponta a ponta no universo real de 2026, onde o 2º turno ainda não aconteceu."""
    rng = np.random.default_rng(semente)
    s = base.secoes
    a_esq, a_dir, a_out = (s[c].to_numpy().astype(float) for c in ("a_esq", "a_dir", "a_outros"))
    validos_1t = a_esq + a_dir + a_out
    p1 = (a_esq + 1) / (a_esq + a_dir + 2)
    ruido = 0.03 * rng.standard_normal(base.n_municipios)[base.mun_idx] + 0.05 * rng.standard_normal(base.n_secoes)
    p2 = 1 / (1 + np.exp(-(np.log(p1 / (1 - p1)) + swing + ruido)))
    validos = rng.binomial(validos_1t.astype(np.int64), 0.98)
    esq = rng.binomial(validos, p2)
    compar = s["a_comparecimento"].to_numpy()
    hora = s["a_hora"].to_numpy() + (rng.exponential(300, base.n_secoes) * 1e6).astype("timedelta64[us]")
    return pl.DataFrame({
        "uf": s["uf"], "mun": s["mun"], "zona": s["zona"], "secao": s["secao"],
        "hora": hora, "aptos": s["aptos"], "comparecimento": compar.astype(np.int32),
        "esq": esq.astype(np.int32), "dir": (validos - esq).astype(np.int32),
        "brancos": ((compar - validos) // 2).clip(0).astype(np.int32),
        "nulos": (compar - validos - (compar - validos) // 2).clip(0).astype(np.int32),
    })
