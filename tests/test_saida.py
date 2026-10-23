import json
from datetime import datetime

import pytest

from eleicao.config import BASES, ELEICOES
from eleicao.saida import Saida
from eleicao.tipos import Base, Faixa, Projecao, Recorte

pytestmark = pytest.mark.skipif(not (BASES / "2026" / "secoes.parquet").exists(), reason="rode `uv run eleicao base` antes")


def projecao(pct: float, apurado: float, pct_uf: float) -> Projecao:
    f = Faixa(50.0, 49.0, 51.0)
    uf = Recorte(pct_uf, pct_uf, apurado, 10, f)
    return Projecao(datetime(2026, 10, 25, 18), Recorte(pct, pct, apurado, 1000, f), {"sp": uf, "ba": uf})


@pytest.fixture(scope="module")
def base():
    return Base.ler(BASES / "2026")


def test_serie_nao_recua_depois_de_reiniciar(base, tmp_path):
    arq = tmp_path / "projecao.json"
    Saida(ELEICOES[2026], base, arq).registrar(projecao(40.0, 46.0, 40.0), "apurando", datetime(2026, 10, 25, 18))
    Saida(ELEICOES[2026], base, arq).registrar(projecao(27.4, 45.9, 20.0), "apurando", datetime(2026, 10, 25, 18, 1))
    serie = json.loads(arq.read_text())["serie"]
    assert [p["pct_secoes"] for p in serie] == [40.0]


def test_uf_sem_um_por_cento_nao_mostra_projecao(base, tmp_path):
    arq = tmp_path / "projecao.json"
    Saida(ELEICOES[2026], base, arq).registrar(projecao(5.0, 46.0, 0.5), "apurando", datetime(2026, 10, 25, 18))
    doc = json.loads(arq.read_text())
    assert doc["serie"][-1]["projecao"] is not None
    assert all(u["projecao"] is None for u in doc["ufs"])
