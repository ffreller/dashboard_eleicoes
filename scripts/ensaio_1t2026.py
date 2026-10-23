"""Ensaio com o 1º turno de 2026: o que o modelo projetaria para Lula × Flávio em cada ponto da apuração.

O alvo é a fração de Lula entre os dois no 1º turno de 2026, seção a seção, na ordem real de chegada.
Como o 1º turno de 2026 não pode ser referência dele mesmo, a base troca de ano: base A é o 1º turno de
2022 na mesma seção (Lula 13 × Bolsonaro 22), base B é o 2º turno de 2022 pareado por local. Seção de 2026
sem a mesma seção em 2022 recebe as taxas por eleitor do seu município em 2022 (ou da UF).

Grava site/dados/exemplo-1t2026.json até 50% das seções. Rode da raiz do repositório:

    uv run python scripts/ensaio_1t2026.py
"""

import json
from datetime import datetime

import numpy as np
import polars as pl

from eleicao.base.abertos import CHAVE, detalhe, votacao
from eleicao.base.pareamento import identificar_locais, parear
from eleicao.config import CAPITAIS, DADOS, ELEICOES, SITE
from eleicao.ensaio import apuracao_ate, postos
from eleicao.modelo import Modelo
from eleicao.saida import Saida, ler_validacao
from eleicao.tipos import COLUNAS_CENARIO, Base

PONTOS = (0.1, 0.25, 0.5, 1, 1.5, 2, 3, 4, 5, 7, 10, 12.5, 15, 17.5, 20, 25, 30, 35, 40, 45, 50)
CONTAGENS = ("esq", "dir", "outros", "brancos", "nulos", "comparecimento")


def votos(ano: int, turno: int, esq: int, dir: int) -> pl.DataFrame:
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


def base_a_2022(alvo: pl.DataFrame) -> pl.DataFrame:
    """1º turno de 2022 em cada seção de `alvo`; sem a mesma seção, taxas por eleitor do município ou da UF."""
    d22 = detalhe(2022).filter(pl.col("turno") == 1).select(CHAVE + ["aptos", "comparecimento", "brancos", "nulos", "hora"])
    a = d22.join(votos(2022, 1, 13, 22).select(CHAVE + ["esq", "dir", "outros"]), on=CHAVE, how="left").with_columns(
        pl.col("esq", "dir", "outros").fill_null(0)
    )

    def taxas(por: list[str]) -> pl.DataFrame:
        return a.group_by(por).agg(*[(pl.col(c).sum() / pl.col("aptos").sum()).alias(f"{c}_{por[-1]}") for c in CONTAGENS])

    j = (
        alvo.select(CHAVE + ["aptos"])
        .join(a.drop("aptos").rename({c: f"{c}_sec" for c in CONTAGENS} | {"hora": "a_hora"}), on=CHAVE, how="left")
        .join(taxas(["uf", "mun"]), on=["uf", "mun"], how="left")
        .join(taxas(["uf"]), on="uf", how="left")
    )

    def estimado(c: str) -> pl.Expr:
        return (pl.coalesce(f"{c}_mun", f"{c}_uf") * pl.col("aptos")).round()

    return j.select(
        *CHAVE,
        pl.col("esq_sec").is_not_null().alias("a_mesma_secao"),
        "a_hora",
        *[pl.coalesce(f"{c}_sec", estimado(c)).cast(pl.Int32).alias(f"a_{c}") for c in CONTAGENS],
    )


def montar() -> tuple[Base, pl.DataFrame]:
    d26 = detalhe(2026).filter(pl.col("turno") == 1)
    v26 = votos(2026, 1, 13, 22)
    cenario = (
        d26.select(CHAVE + ["hora", "aptos", "comparecimento", "brancos", "nulos"])
        .join(v26.select(CHAVE + ["esq", "dir"]), on=CHAVE, how="left")
        .with_columns(pl.col("esq", "dir").fill_null(0).cast(pl.Int32))
        .select(list(COLUNAS_CENARIO))
    )
    a = base_a_2022(d26)
    print(f"base A: {a['a_mesma_secao'].mean():.1%} das seções de 2026 acharam a mesma seção em 2022")

    anterior = identificar_locais(votos(2022, 2, 13, 22))
    alvo = identificar_locais(d26.select(CHAVE + ["local", "nm_local", "endereco"]))
    secoes = (
        d26.select(CHAVE + ["aptos"])
        .join(a.drop("a_mesma_secao"), on=CHAVE, how="left")
        .join(parear(alvo, anterior), on=CHAVE, how="left")
    )
    municipios = (
        d26.group_by("uf", "mun").agg(pl.col("nm_mun").first().alias("nome"))
        .with_columns(pl.col("mun").is_in(list(CAPITAIS)).alias("capital"))
    )
    base = Base.de_tabelas(secoes, municipios)
    cenario = base.secoes.select(CHAVE).join(cenario, on=CHAVE, how="left", maintain_order="left")
    return base, cenario


base, cenario = montar()
final = 100 * cenario["esq"].sum() / (cenario["esq"].sum() + cenario["dir"].sum())
posto = postos(cenario, "real")
horas = np.sort(cenario["hora"].drop_nulls().to_numpy())
modelo = Modelo(base)
destino = SITE / "dados" / "exemplo-1t2026.json"
destino.unlink(missing_ok=True)
saida = Saida(ELEICOES[2026], base, destino, ler_validacao(DADOS / "ensaio"))
for pct in PONTOS:
    limite = int(np.ceil(cenario.height * pct / 100))
    momento = datetime.fromisoformat(str(horas[limite - 1])[:19])
    proj = modelo.projetar(apuracao_ate(base, cenario, posto, limite, momento))
    saida.registrar(proj, "apurando", momento)
    f = proj.brasil.projecao
    if f:
        print(f"{pct:5.1f}% {momento:%H:%M} apurado {proj.brasil.apurado:.2f} projeção {f.centro:.2f} "
              f"[{f.baixo:.2f}, {f.alto:.2f}] chance {f.chance:.1f}% erro {f.centro - final:+.2f}pp")

doc = json.loads(destino.read_text(encoding="utf-8"))
doc["exemplo"] = True
destino.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print(f"final real do 1º turno de 2026, Lula entre os dois: {final:.2f}%")
