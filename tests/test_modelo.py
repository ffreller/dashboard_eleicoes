from datetime import datetime

import numpy as np
import pytest

from eleicao.config import BASES
from eleicao.ensaio import apuracao_ate, cenario_sintetico, postos
from eleicao.modelo import Modelo, Parametros
from eleicao.tipos import Base

pytestmark = pytest.mark.skipif(not (BASES / "2026" / "secoes.parquet").exists(), reason="rode `uv run eleicao base` antes")
MOMENTO = datetime(2026, 10, 25, 19)


@pytest.fixture(scope="module")
def base():
    return Base.ler(BASES / "2026")


@pytest.fixture(scope="module")
def cenario(base):
    return cenario_sintetico(base, swing=0.1, semente=3)


@pytest.fixture(scope="module")
def modelo(base):
    return Modelo(base, Parametros(sorteios=30))


def final(cen):
    return 100 * cen["esq"].sum() / (cen["esq"].sum() + cen["dir"].sum())


def test_apuracao_completa_vira_o_resultado(base, cenario, modelo):
    ap = apuracao_ate(base, cenario, postos(cenario, "real"), cenario.height, MOMENTO)
    p = modelo.projetar(ap).brasil
    assert p.pct_secoes == pytest.approx(100)
    assert p.projecao.centro == pytest.approx(final(cenario), abs=1e-9)
    assert p.projecao.alto - p.projecao.baixo == pytest.approx(0, abs=1e-9)


@pytest.mark.parametrize("ordem", ["real", "aleatoria", "invertida"])
def test_projecao_acha_o_swing_com_dez_por_cento(base, cenario, modelo, ordem):
    ap = apuracao_ate(base, cenario, postos(cenario, ordem), cenario.height // 10, MOMENTO)
    p = modelo.projetar(ap).brasil
    assert abs(p.projecao.centro - final(cenario)) < 0.15
    assert p.projecao.baixo <= final(cenario) <= p.projecao.alto


def test_arquivo_de_resultado_atrasado_em_relacao_ao_de_secoes(base, cenario, modelo):
    """O arquivo de seções já marca 12% das seções, mas o de resultado ainda soma só 10%."""
    posto = postos(cenario, "real")
    resultado = apuracao_ate(base, cenario, posto, cenario.height // 10, MOMENTO)
    secoes = apuracao_ate(base, cenario, posto, int(cenario.height * 0.12), MOMENTO)
    ap = type(resultado)(**{**resultado.__dict__, "totalizada": secoes.totalizada})
    p = modelo.projetar(ap).brasil
    assert abs(p.projecao.centro - final(cenario)) < 0.2


def test_sem_nada_apurado_nao_projeta(base, cenario, modelo):
    ap = apuracao_ate(base, cenario, postos(cenario, "real"), 0, MOMENTO)
    p = modelo.projetar(ap)
    assert p.brasil.projecao is None and p.brasil.apurado is None
    assert all(r.projecao is None for r in p.ufs.values())


def test_faixa_estreita_conforme_a_apuracao_avanca(base, cenario, modelo):
    posto = postos(cenario, "real")
    larguras = []
    for frac in (0.1, 0.5, 0.9):
        f = modelo.projetar(apuracao_ate(base, cenario, posto, int(cenario.height * frac), MOMENTO)).brasil.projecao
        larguras.append(f.alto - f.baixo)
    assert larguras[0] > larguras[1] > larguras[2] > 0
    assert np.all(np.isfinite(larguras))


def test_mesma_apuracao_da_mesma_faixa(base, cenario, modelo):
    ap = apuracao_ate(base, cenario, postos(cenario, "real"), cenario.height // 5, MOMENTO)
    assert modelo.projetar(ap).brasil.projecao == modelo.projetar(ap).brasil.projecao


def test_municipio_completo_no_resultado_nao_projeta_resto(base, cenario, modelo):
    """O 2º turno pode ter menos aptos que o 1º; com todas as seções contadas, a projeção é o apurado."""
    ap = apuracao_ate(base, cenario, postos(cenario, "real"), cenario.height, MOMENTO)
    ap = type(ap)(**{**ap.__dict__, "aptos": (ap.aptos * 0.99).astype(ap.aptos.dtype)})
    for r in modelo.projetar(ap).ufs.values():
        assert r.projecao.centro == pytest.approx(r.apurado, abs=1e-9)
