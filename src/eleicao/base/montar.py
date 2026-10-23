"""Monta data/base/{ano}/: as seções do 2º turno com as duas bases, os municípios e, se o 2º turno
já aconteceu, o cenário real dele (para o ensaio e para o TSE falso)."""

import polars as pl

from eleicao.base.abertos import CHAVE, detalhe, votacao
from eleicao.base.pareamento import identificar_locais, parear
from eleicao.config import BASES, CAPITAIS, ELEICOES
from eleicao.tipos import COLUNAS_CENARIO, Base


def _votos(ano: int, turno: int, esq: int, dir: int) -> pl.DataFrame:
    """Por seção: votos de `esq`, de `dir`, dos demais candidatos, e o local de votação."""
    v = votacao(ano).filter(pl.col("turno") == turno)
    nominal = ~pl.col("numero").is_in([95, 96, 97])
    return v.group_by(CHAVE).agg(
        pl.col("votos").filter(pl.col("numero") == esq).sum().alias("esq"),
        pl.col("votos").filter(pl.col("numero") == dir).sum().alias("dir"),
        pl.col("votos").filter(nominal & ~pl.col("numero").is_in([esq, dir])).sum().alias("outros"),
        pl.col("local").first(),
        pl.col("nm_local").first(),
        pl.col("endereco").first(),
    )


def montar(ano: int) -> Base:
    e = ELEICOES[ano]
    esq, dir = e.esquerda.numero, e.direita.numero
    det = detalhe(ano)
    tem_2t = det.filter(pl.col("turno") == 2).height > 0
    universo = det.filter(pl.col("turno") == (2 if tem_2t else 1))

    a = (
        det.filter(pl.col("turno") == 1)
        .select(CHAVE + ["aptos", "comparecimento", "brancos", "nulos", "hora"])
        .join(_votos(ano, 1, esq, dir).select(CHAVE + ["esq", "dir", "outros"]), on=CHAVE, how="left")
        .with_columns(pl.col("esq", "dir", "outros").fill_null(0))
        .rename({
            "esq": "a_esq", "dir": "a_dir", "outros": "a_outros", "brancos": "a_brancos", "nulos": "a_nulos",
            "comparecimento": "a_comparecimento", "hora": "a_hora",
        })
    )
    secoes = universo.select(CHAVE).join(a, on=CHAVE, how="left")
    sem_a = secoes.filter(pl.col("aptos").is_null())
    if sem_a.height:
        raise ValueError(f"{sem_a.height} seções do 2º turno sem a mesma seção no 1º turno: {sem_a.head(5)}")

    b_esq, b_dir = e.numeros_b
    anterior = identificar_locais(_votos(e.ano_b, 2, b_esq, b_dir))
    alvo = identificar_locais(universo.select(CHAVE + ["local", "nm_local", "endereco"]))
    secoes = secoes.join(parear(alvo, anterior), on=CHAVE, how="left")

    municipios = (
        universo.group_by("uf", "mun").agg(pl.col("nm_mun").first().alias("nome"))
        .with_columns(pl.col("mun").is_in(list(CAPITAIS)).alias("capital"))
    )
    base = Base.de_tabelas(secoes.with_columns(pl.col(c).cast(pl.Int32) for c in ("a_esq", "a_dir", "a_outros")), municipios)
    pasta = BASES / str(ano)
    base.gravar(pasta)

    peso = base.secoes["aptos"].sum()
    print(f"base {ano}: {base.n_secoes} seções, {base.n_municipios} municípios, {peso} aptos")
    print(base.secoes.group_by("b_nivel").agg(pl.len(), (100 * pl.col("aptos").cast(pl.Float64).sum() / peso).round(2).alias("pct_aptos")).sort("b_nivel"))

    if tem_2t:
        cenario = (
            universo.select(CHAVE + ["hora", "aptos", "comparecimento", "brancos", "nulos"])
            .join(_votos(ano, 2, esq, dir).select(CHAVE + ["esq", "dir"]), on=CHAVE, how="left")
            .with_columns(pl.col("esq", "dir").fill_null(0).cast(pl.Int32))
            .select(list(COLUNAS_CENARIO))
        )
        cenario.write_parquet(pasta / "cenario.parquet")
        print(f"cenário {ano}: {cenario.height} seções, {cenario['esq'].sum()} x {cenario['dir'].sum()}")
    return base
