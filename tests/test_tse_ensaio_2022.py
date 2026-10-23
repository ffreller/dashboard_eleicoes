"""O TSE falso servindo o 2º turno real de 2022 na escala nacional. Pula se a base de 2022 não existe."""

import asyncio
import os
from datetime import timedelta
from pathlib import Path

import polars as pl
import pytest
from tse_sintetico import esperado, rodar_ciclos, somas

from eleicao import config
from eleicao.tipos import Base
from eleicao.tse.apuracao import Estado
from eleicao.tse.falso import Falhas, TseFalso

PASTA = Path(os.environ.get("ELEICAO_BASE_2022", config.BASES / "2022"))
pytestmark = pytest.mark.skipif(not (PASTA / "cenario.parquet").exists(), reason="base de 2022 ausente")


def test_falso_em_escala_nacional_fecha_com_o_cenario_real():
    base = Base.ler(PASTA)
    cenario = pl.read_parquet(PASTA / "cenario.parquet")
    primeira = cenario["hora"].min()
    estado = Estado()
    with TseFalso(2022, pasta=PASTA, falhas=Falhas(p_404=0.02, p_500=0.02, p_truncado=0.01, semente=1)) as falso:
        for horas in (1, 3, 5, 9):
            relogio = primeira + timedelta(hours=horas)
            falso.relogio.fixar(relogio)
            asyncio.run(rodar_ciclos(falso.url_base, base, estado, 2, ano=2022, espera=0.001))
        falso.falhas = None
        [montagem] = asyncio.run(rodar_ciclos(falso.url_base, base, estado, 1, ano=2022))
    assert montagem.secoes_fora_da_base == 0 and montagem.municipios_fora_da_base == 0
    assert somas(montagem.apuracao) == esperado(cenario, relogio)
