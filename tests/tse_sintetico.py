"""Cenário e Base sintéticos sobre o universo real de seções do Acre, com votos e horas inventados."""

import dataclasses
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from eleicao import config
from eleicao.modelo import recortes_apurados
from eleicao.tipos import COLUNAS_BASE, COLUNAS_CENARIO, COLUNAS_MUNICIPIOS, Apuracao, Base, Projecao
from eleicao.tse.ao_vivo import ciclo
from eleicao.tse.apuracao import Estado, montar
from eleicao.tse.cliente import Cliente

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


class ModeloApurado:
    """Estande do `eleicao.modelo.Modelo`: só reporta o apurado."""

    def __init__(self, base: Base) -> None:
        self.base = base

    def projetar(self, ap: Apuracao) -> Projecao:
        brasil, ufs = recortes_apurados(self.base, ap)
        return Projecao(momento=ap.momento, brasil=brasil, ufs=ufs)


def esperado(cenario: pl.DataFrame, relogio: datetime) -> dict:
    feito = cenario.filter(pl.col("hora") <= relogio)
    return {
        "esq": feito["esq"].sum(), "dir": feito["dir"].sum(), "brancos": feito["brancos"].sum(),
        "nulos": feito["nulos"].sum(), "comparecimento": feito["comparecimento"].sum(),
        "aptos": feito["aptos"].sum(), "secoes": feito.height, "totalizada": feito.height,
    }


def somas(ap) -> dict:
    return {
        "esq": ap.esq.sum(), "dir": ap.dir.sum(), "brancos": ap.brancos.sum(), "nulos": ap.nulos.sum(),
        "comparecimento": ap.comparecimento.sum(), "aptos": ap.aptos.sum(), "secoes": ap.secoes.sum(),
        "totalizada": ap.totalizada.sum(),
    }


async def rodar_ciclos(url_base: str, base: Base, estado: Estado, n: int, ano: int = 2026, **cliente) -> list:
    eleicao = config.ELEICOES[ano]
    div = dataclasses.replace(eleicao.divulgacao, url_base=url_base)
    montagens = []
    async with Cliente(por_segundo=1e6, **cliente) as c:
        for _ in range(n):
            await ciclo(c, div, eleicao, estado)
            montagens.append(montar(base, estado, datetime(2026, 10, 25, 12)))
    return montagens
