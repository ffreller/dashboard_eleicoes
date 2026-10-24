"""Calibração da faixa no início da apuração: erro padronizado z = (final − centro) / (largura / 3,92).

Roda os ensaios do 2º turno de 2018 e 2022 e o do 1º turno de 2026 (Lula × Flávio) nas três ordens de
chegada e agrupa z por fase da apuração, no Brasil e em cada UF ainda aberta. Faixa bem calibrada dá
raiz da média de z² perto de 1 e cobertura perto de 95%. Parâmetros do modelo podem ser trocados na linha de comando:

    uv run python scripts/calibrar_inicio.py sd_ordem_uf=0.03

`ate=10` limita aos pontos até 10% apurado, para varrer parâmetros mais rápido.
"""

import sys

import numpy as np
import polars as pl
from ensaio_1t2026 import montar

from eleicao.ensaio import ORDENS, PONTOS_PCT, rodar
from eleicao.modelo import Parametros

FASES = ((0, 1), (1, 5), (5, 20), (20, 100))

opcoes = {k: float(v) for k, v in (a.split("=") for a in sys.argv[1:])}
pontos = tuple(p for p in PONTOS_PCT if p <= opcoes.pop("ate", 100))
parametros = Parametros(**opcoes)
base26, cen26 = montar()
cen26 = cen26.with_columns(pl.col("hora").fill_null(pl.col("hora").max()))
eleicoes = {"2T 2018": {"ano": 2018}, "2T 2022": {"ano": 2022}, "1T 2026": {"ano": 2026, "base": base26, "cen": cen26}}

tabelas = []
for nome, args in eleicoes.items():
    for ordem in ORDENS:
        df = rodar(ordem=ordem, parametros=parametros, pontos=pontos, **args).with_columns(pl.lit(nome).alias("eleicao"))
        tabelas.append(df.with_columns(((pl.col("final") - pl.col("centro")) / ((pl.col("alto") - pl.col("baixo")) / 3.92)).alias("z")))
tudo = pl.concat(tabelas)


def linha(d: pl.DataFrame) -> dict:
    z_uf = np.concatenate([np.asarray(z, dtype=float) for z in d["z_uf"].to_list()] or [np.zeros(0)])
    return {
        "pontos": d.height, "z_rms": float(np.sqrt(np.mean(d["z"].to_numpy() ** 2))),
        "z_max": float(d["z"].abs().max()), "cobre": float(d["cobre"].mean()),
        "uf_n": len(z_uf), "uf_z_rms": float(np.sqrt(np.mean(z_uf**2))) if len(z_uf) else None,
        "uf_cobre": float(np.mean(np.abs(z_uf) <= 1.96)) if len(z_uf) else None,
        "uf_z_gt3": float(np.mean(np.abs(z_uf) > 3)) if len(z_uf) else None,
    }


linhas = []
for nome in [*eleicoes, "todas"]:
    d_el = tudo if nome == "todas" else tudo.filter(pl.col("eleicao") == nome)
    for lo, hi in FASES:
        d = d_el.filter((pl.col("pct_secoes") > lo) & (pl.col("pct_secoes") <= hi))
        if d.height:
            linhas.append({"eleicao": nome, "fase": f"{lo}–{hi}%", **linha(d)})

pl.Config.set_tbl_rows(40)
pl.Config.set_tbl_width_chars(200)
print(parametros)
print(pl.DataFrame(linhas).with_columns(pl.col(pl.Float64).round(3)))
print(tudo.filter(pl.col("pct_secoes") <= 2).select(
    "eleicao", "ordem", pl.col("pct_secoes").round(2), pl.col("z").round(2), pl.col("chance_perdedor").round(1),
    pl.col("cobertura_uf").round(2),
))
