import asyncio
import dataclasses
import json
from datetime import timedelta
from pathlib import Path

import polars as pl
import pytest
from tse_sintetico import ABERTURA, ModeloApurado, esperado, gravar_sintetico, rodar_ciclos, somas

from eleicao import config
from eleicao.tipos import Base
from eleicao.tse.ao_vivo import ciclo, fase_da_contagem, rodar
from eleicao.tse.apuracao import Estado
from eleicao.tse.cliente import Cliente
from eleicao.tse.falso import Falhas, TseFalso

ELEICAO = config.ELEICOES[2026]


@pytest.fixture
def mundo(tmp_path: Path):
    pasta = tmp_path / "2026"
    cenario = gravar_sintetico(pasta)
    with TseFalso(2026, pasta=pasta) as falso:
        yield falso, pasta, cenario, tmp_path / "projecao.json"


@pytest.mark.parametrize("minutos", [60, 130, 400])
def test_apuracao_fecha_com_a_soma_do_cenario(mundo, minutos):
    falso, pasta, cenario, _ = mundo
    base = Base.ler(pasta)
    relogio = ABERTURA + timedelta(minutes=minutos)
    falso.relogio.fixar(relogio)
    [montagem] = asyncio.run(rodar_ciclos(falso.url_base, base, Estado(), 1))
    assert montagem.secoes_fora_da_base == 0 and montagem.municipios_fora_da_base == 0
    assert somas(montagem.apuracao) == esperado(cenario, relogio)
    assert montagem.apuracao.momento == cenario.filter(pl.col("hora") <= relogio)["hora"].max()


def test_segundo_ciclo_so_baixa_o_que_mudou(mundo):
    falso = mundo[0]
    falso.relogio.fixar(ABERTURA + timedelta(minutes=90))

    async def duas_vezes():
        div = dataclasses.replace(ELEICAO.divulgacao, url_base=falso.url_base)
        async with Cliente(por_segundo=1e6) as c:
            await ciclo(c, div, ELEICAO, estado := Estado())
            primeiro = c.retirar_medidas()
            await ciclo(c, div, ELEICAO, estado)
            return primeiro, c.retirar_medidas()

    primeiro, segundo = asyncio.run(duas_vezes())
    assert primeiro.novos > 50 and segundo.novos == 0
    assert segundo.iguais == 28 * 2
    assert segundo.requisicoes == 56


@pytest.mark.parametrize(("minutos", "fase", "pct"), [(-30, "aguardando", None), (100, "apurando", None), (400, "encerrada", 100.0)])
def test_rodar_grava_fase_e_percentual_de_secoes(mundo, minutos, fase, pct):
    falso, pasta, cenario, destino = mundo
    relogio = ABERTURA + timedelta(minutes=minutos)
    falso.relogio.fixar(relogio)
    rodar(2026, 0, falso.url_base, pasta=pasta, destino=destino, ciclos=2, modelo=ModeloApurado, por_segundo=1e6)
    doc = json.loads(destino.read_text(encoding="utf-8"))
    assert doc["fase"] == fase
    if fase == "aguardando":
        assert doc["serie"] == [] and doc["ufs"] == []
        return
    feitas = cenario.filter(pl.col("hora") <= relogio).height
    ultimo = doc["serie"][-1]
    assert ultimo["pct_secoes"] == pytest.approx(pct or 100 * feitas / cenario.height, abs=0.005)
    feito = cenario.filter(pl.col("hora") <= relogio)
    assert ultimo["apurado"] == pytest.approx(100 * feito["esq"].sum() / (feito["esq"].sum() + feito["dir"].sum()), abs=0.005)
    assert [u["uf"] for u in doc["ufs"]] == ["AC"]


def test_com_falhas_o_laco_sobrevive_nunca_regride_e_converge(mundo):
    falso, pasta, cenario, _ = mundo
    base = Base.ler(pasta)
    falso.falhas = Falhas(p_404=0.15, p_500=0.15, p_truncado=0.1, semente=3)
    estado = Estado()
    vistos = []
    for minutos in (20, 45, 80, 120, 170, 400):
        falso.relogio.fixar(ABERTURA + timedelta(minutes=minutos))
        vistos += asyncio.run(rodar_ciclos(falso.url_base, base, estado, 4, espera=0.001, tentativas=2))
    contagens = [(m.apuracao.totalizada.sum(), m.apuracao.secoes.sum(), m.apuracao.esq.sum()) for m in vistos]
    assert contagens == sorted(contagens)

    falso.falhas = None
    final = asyncio.run(rodar_ciclos(falso.url_base, base, estado, 3, espera=0.001))
    assert somas(final[-1].apuracao) == esperado(cenario, ABERTURA + timedelta(minutes=400))
    assert fase_da_contagem(final[-1].apuracao, estado) == "encerrada"


def test_resultado_atrasado_e_relido_ate_alcancar_as_secoes(mundo):
    falso, pasta, cenario, _ = mundo
    base = Base.ler(pasta)
    falso.falhas = Falhas(p_404=0, p_500=0, p_truncado=0, atraso_resultado=True)
    relogio = ABERTURA + timedelta(minutes=100)
    falso.relogio.fixar(relogio)
    [montagem] = asyncio.run(rodar_ciclos(falso.url_base, base, Estado(), 1))
    ap = montagem.apuracao
    assert ap.totalizada.sum() == cenario.filter(pl.col("hora") <= relogio).height
    assert ap.secoes.sum() == cenario.filter(pl.col("hora") <= relogio - timedelta(seconds=falso.passo)).height

    falso.falhas = None
    [montagem] = asyncio.run(rodar_ciclos(falso.url_base, base, Estado(), 1))
    assert montagem.apuracao.secoes.sum() == montagem.apuracao.totalizada.sum()
