"""Cenário e Base sintéticos sobre o universo real de seções do Acre, com votos e horas inventados."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from eleicao.tipos import COLUNAS_BASE, COLUNAS_CENARIO, COLUNAS_MUNICIPIOS, Base

FIXTURES = Path(__file__).parent / "fixtures" / "tse"
ABERTURA = datetime(2026, 10, 25, 17, 0, 0)


def gravar_sintetico(pasta: Path, semente: int = 7) -> pl.DataFrame:
    """Grava secoes/municipios/cenario.parquet em `pasta` e devolve o cenário."""
    cs = json.loads((FIXTURES / "ac-p003220-cs.json").read_text(encoding="utf-8"))
    linhas, nomes = [], []
    for mu in cs["abr"][0]["mu"]:
        nomes.append(("ac", int(mu["cd"]), mu["nm"], False))
        for zon in mu["zon"]:
            for sec in zon["sec"]:
                if "nsp" not in sec:
                    linhas.append(("ac", int(mu["cd"]), int(zon["cd"]), int(sec["ns"])))
    rng = np.random.default_rng(semente)
    n = len(linhas)
    aptos = rng.integers(120, 420, n)
    comparecimento = (aptos * rng.uniform(0.6, 0.9, n)).astype(int)
    brancos = (comparecimento * rng.uniform(0.005, 0.02, n)).astype(int)
    nulos = (comparecimento * rng.uniform(0.01, 0.04, n)).astype(int)
    validos = comparecimento - brancos - nulos
    esq = (validos * rng.uniform(0.2, 0.7, n)).astype(int)
    minutos = np.sort(rng.integers(0, 200, n))
    uf, mun, zona, secao = zip(*linhas, strict=True)
    cenario = pl.DataFrame({
        "uf": uf, "mun": mun, "zona": zona, "secao": secao,
        "hora": [ABERTURA + timedelta(minutes=int(m), seconds=int(m) % 53) for m in minutos],
        "aptos": aptos, "comparecimento": comparecimento, "esq": esq, "dir": validos - esq,
        "brancos": brancos, "nulos": nulos,
    }).cast({k: v for k, v in COLUNAS_CENARIO.items() if k != "hora"}).cast({"hora": pl.Datetime})
    municipios = pl.DataFrame(nomes, schema=list(COLUNAS_MUNICIPIOS), orient="row").cast(COLUNAS_MUNICIPIOS)
    secoes = pl.DataFrame({
        "uf": uf, "mun": mun, "zona": zona, "secao": secao, "aptos": aptos,
        "a_esq": esq, "a_dir": validos - esq, "a_outros": rng.integers(0, 20, n),
        "a_brancos": brancos, "a_nulos": nulos, "a_comparecimento": comparecimento,
        "a_hora": cenario["hora"], "b_p": rng.uniform(0.3, 0.7, n), "b_nivel": [1] * n,
    }).cast({k: v for k, v in COLUNAS_BASE.items() if k != "a_hora"})
    Base.de_tabelas(secoes, municipios).gravar(pasta)
    cenario.write_parquet(pasta / "cenario.parquet")
    return cenario
