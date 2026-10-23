"""Pareamento das seções de uma eleição com o 2º turno da eleição anterior.

Seções são renumeradas e trocam de local entre eleições, então o pareamento desce uma escada e
cada seção fica no primeiro degrau que a encontra:

0. mesma seção (UF, município, zona, número) e mesmo local (nome, endereço ou número do local);
1. mesmo local (nome ou endereço normalizado) no mesmo município: soma das seções desse local;
2. mesma seção, mas o local mudou e não foi achado pelo nome;
3. mesma zona do mesmo município;
4. mesmo município;
5. mesma UF.

Em todos os degraus a fração da esquerda é suavizada em direção à da zona (ou do degrau de cima)
e limitada a [1%, 99%], para que seções com poucos votos não produzam frações extremas.
"""

import polars as pl

from eleicao.base.abertos import CHAVE

SUAVIZACAO = 10.0
"""Votos fictícios, na proporção da zona, somados a cada unidade pareada."""


def _normal(c: str) -> pl.Expr:
    return (
        pl.col(c).str.to_uppercase().str.normalize("NFKD").str.replace_all(r"[^\x00-\x7F]", "")
        .str.replace_all(r"[^A-Z0-9 ]", " ").str.replace_all(r"\s+", " ").str.strip_chars()
    )


def identificar_locais(df: pl.DataFrame) -> pl.DataFrame:
    """Normaliza nome e endereço do local de votação para comparar entre eleições."""
    return df.with_columns(_normal("nm_local").alias("nome"), _normal("endereco").alias("end"))


def parear(alvo: pl.DataFrame, anterior: pl.DataFrame) -> pl.DataFrame:
    """Para cada seção de `alvo`, a fração da esquerda (`b_p`) no 2º turno anterior e o degrau (`b_nivel`).

    `alvo`: CHAVE + local, nome, end (uma linha por seção). `anterior`: CHAVE + local, nome, end, esq, dir.
    """
    ant = anterior.filter((pl.col("esq") + pl.col("dir")) > 0)

    def agregado(por: list[str], nome: str) -> pl.DataFrame:
        return ant.group_by(por).agg(pl.col("esq").sum().alias(f"{nome}_esq"), pl.col("dir").sum().alias(f"{nome}_dir"))

    uf, mun, zona = agregado(["uf"], "uf"), agregado(["uf", "mun"], "mun"), agregado(["uf", "mun", "zona"], "zona")
    por_nome = agregado(["uf", "mun", "nome"], "pnome")
    por_end = agregado(["uf", "mun", "end"], "pend")
    secao = ant.select(CHAVE + ["local", "nome", "end", "esq", "dir"]).rename(
        {"local": "local_b", "nome": "nome_b", "end": "end_b", "esq": "sec_esq", "dir": "sec_dir"}
    )

    j = (
        alvo.select(CHAVE + ["local", "nome", "end"])
        .join(secao, on=CHAVE, how="left")
        .join(por_nome, on=["uf", "mun", "nome"], how="left")
        .join(por_end, on=["uf", "mun", "end"], how="left")
        .join(zona, on=["uf", "mun", "zona"], how="left")
        .join(mun, on=["uf", "mun"], how="left")
        .join(uf, on=["uf"], how="left")
    )
    mesma_secao = pl.col("sec_esq").is_not_null()
    mesmo_local = (pl.col("nome") == pl.col("nome_b")) | (pl.col("end") == pl.col("end_b")) | (pl.col("local") == pl.col("local_b"))
    local_esq = pl.coalesce("pnome_esq", "pend_esq")
    local_dir = pl.coalesce("pnome_dir", "pend_dir")
    degraus = [
        (mesma_secao & mesmo_local, pl.col("sec_esq"), pl.col("sec_dir")),
        (local_esq.is_not_null(), local_esq, local_dir),
        (mesma_secao, pl.col("sec_esq"), pl.col("sec_dir")),
        (pl.col("zona_esq").is_not_null(), pl.col("zona_esq"), pl.col("zona_dir")),
        (pl.col("mun_esq").is_not_null(), pl.col("mun_esq"), pl.col("mun_dir")),
        (pl.col("uf_esq").is_not_null(), pl.col("uf_esq"), pl.col("uf_dir")),
    ]

    nivel = pl.coalesce(*[pl.when(c).then(pl.lit(n, pl.Int8)) for n, (c, _, _) in enumerate(degraus)])
    esq = pl.coalesce(*[pl.when(c).then(e) for c, e, _ in degraus]).cast(pl.Float64)
    dir_ = pl.coalesce(*[pl.when(c).then(d) for c, _, d in degraus]).cast(pl.Float64)
    pai = pl.coalesce(
        pl.col("zona_esq") / (pl.col("zona_esq") + pl.col("zona_dir")),
        pl.col("mun_esq") / (pl.col("mun_esq") + pl.col("mun_dir")),
        pl.col("uf_esq") / (pl.col("uf_esq") + pl.col("uf_dir")),
    )
    out = j.select(
        *CHAVE,
        ((esq + SUAVIZACAO * pai) / (esq + dir_ + SUAVIZACAO)).clip(0.01, 0.99).alias("b_p"),
        nivel.alias("b_nivel"),
    )
    if out["b_p"].null_count():
        raise ValueError(f"{out['b_p'].null_count()} seções sem nenhum pareamento, nem pela UF")
    return out
