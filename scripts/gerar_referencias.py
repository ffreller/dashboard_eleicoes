"""Curvas de referência da diferença Lula − adversário (só entre os dois) por % de seções apuradas.

Grava site/dados/referencias.json com o 1º turno de 2026 e o 2º turno de 2022, na ordem real de chegada.
Rode da raiz do repositório:

    uv run python scripts/gerar_referencias.py
"""

import json
import math

import numpy as np
import polars as pl

from eleicao.base.abertos import CHAVE, detalhe, votos_por_secao
from eleicao.config import DADOS, SITE

GRADE = [round(float(p), 1) for p in np.arange(0.1, 2.01, 0.1)] + [float(p) for p in np.arange(2.5, 100.01, 0.5)]
CONTROLE = (1, 10, 50, 90, 100)


def votos_1t2026() -> pl.DataFrame:
    agg = votos_por_secao(2026, 1, 13, 22).select(CHAVE + ["esq", "dir"])
    d = detalhe(2026).filter(pl.col("turno") == 1).select(CHAVE + ["hora"])
    return d.join(agg, on=CHAVE, how="left").with_columns(pl.col("esq", "dir").fill_null(0))


def curva(df: pl.DataFrame) -> list[list[float]]:
    df = df.sort("hora", nulls_last=True)
    esq = df["esq"].cast(pl.Int64).cum_sum().to_numpy()
    dir = df["dir"].cast(pl.Int64).cum_sum().to_numpy()
    n = len(df)
    pontos = []
    for p in GRADE:
        k = min(math.ceil(n * p / 100) - 1, n - 1)
        pontos.append([p, round(100 * (int(esq[k]) - int(dir[k])) / (int(esq[k]) + int(dir[k])), 2)])
    return pontos


curvas = [
    {"id": "1t2026", "rotulo": "1º turno de 2026", "pontos": curva(votos_1t2026())},
    {"id": "2t2022", "rotulo": "2º turno de 2022", "pontos": curva(pl.read_parquet(DADOS / "base" / "2022" / "cenario.parquet"))},
]
(SITE / "dados" / "referencias.json").write_text(json.dumps({"curvas": curvas}, ensure_ascii=False, separators=(",", ":")))
for c in curvas:
    por_p = dict(c["pontos"])
    print(c["id"], {p: por_p[float(p)] for p in CONTROLE})
