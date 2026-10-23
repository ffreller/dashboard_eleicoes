import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from eleicao.tse.arquivos import ArquivoInesperado, ler_andamento, ler_resultado, ler_secoes

FIXTURES = Path(__file__).parent / "fixtures" / "tse"
ESQ, DIR = 13, 22


def carregar(nome: str) -> dict:
    return json.loads((FIXTURES / nome).read_text(encoding="utf-8"))


def test_secoes_do_primeiro_turno_trazem_hora_e_pulam_agregadas():
    secoes = ler_secoes("ac", carregar("ac-p003220-cs.json"))
    assert len(secoes.secao) == 2270
    assert secoes.n_totalizadas == 2270
    porto_walter = (secoes.mun == 1066) & (secoes.zona == 4) & (secoes.secao == 77)
    assert secoes.hora[porto_walter] == np.datetime64(datetime(2026, 10, 4, 21, 8, 17), "s")


def test_secao_agregada_nao_entra_e_a_principal_que_a_carrega_sim():
    cs = carregar("ac-p003220-cs.json")
    secoes = ler_secoes("ac", cs)
    pares = {(int(m), int(z), int(s)) for m, z, s in zip(secoes.mun, secoes.zona, secoes.secao)}
    nsp, nsa = [], []
    for mu in cs["abr"][0]["mu"]:
        for zon in mu["zon"]:
            for s in zon["sec"]:
                chave = (int(mu["cd"]), int(zon["cd"]), int(s["ns"]))
                if "nsp" in s:
                    nsp.append(chave)
                if "nsa" in s:
                    nsa.append(chave)
    assert len(nsp) == 141 and len(nsa) == 129
    assert not pares & set(nsp)
    assert set(nsa) <= pares


def test_secoes_antes_da_apuracao_nao_tem_hora():
    secoes = ler_secoes("ac", carregar("ac-p003221-cs.json"))
    assert len(secoes.secao) == 2270
    assert secoes.n_totalizadas == 0
    assert np.isnat(secoes.hora).all()


def test_andamento_lista_so_municipios():
    andamento = ler_andamento(carregar("ac-e006257-ab.json"))
    assert len(andamento) == 22
    assert sum(a.secoes_totalizadas for a in andamento.values()) == 2270
    assert sum(a.secoes_total for a in andamento.values()) == 2270
    assert andamento[1007].atualizado == datetime(2026, 10, 4, 17, 17, 32)
    assert ler_andamento(carregar("br-e006257-ab.json")) == {}


def test_andamento_antes_da_apuracao_esta_zerado():
    andamento = ler_andamento(carregar("ac-e006258-ab.json"))
    assert len(andamento) == 22
    assert all(a.secoes_totalizadas == 0 and a.atualizado is None for a in andamento.values())
    assert sum(a.aptos_total for a in andamento.values()) > 0


def somar_municipios() -> dict[str, int]:
    soma = dict.fromkeys(("esq", "dir", "brancos", "nulos", "comparecimento", "aptos", "secoes"), 0)
    arquivos = sorted(FIXTURES.glob("ac0*-c0001-e006257-u.json"))
    assert len(arquivos) == 22
    for arquivo in arquivos:
        r = ler_resultado(json.loads(arquivo.read_text(encoding="utf-8")), ESQ, DIR)
        for campo in soma:
            soma[campo] += getattr(r, campo)
    return soma


def test_soma_dos_municipios_do_acre_fecha_com_o_arquivo_da_uf():
    uf = ler_resultado(carregar("ac-c0001-e006257-u.json"), ESQ, DIR)
    assert somar_municipios() == {
        "esq": uf.esq, "dir": uf.dir, "brancos": uf.brancos, "nulos": uf.nulos,
        "comparecimento": uf.comparecimento, "aptos": uf.aptos, "secoes": uf.secoes,
    }
    assert (uf.esq, uf.dir) == (134770, 302807)


def test_resultado_fecha_votos_e_comparecimento():
    for nome in ("ac-c0001-e006257-u.json", "ac01007-c0001-e006257-u.json"):
        dados = carregar(nome)
        r = ler_resultado(dados, ESQ, DIR)
        assert r.comparecimento == int(dados["v"]["vvc"]) + r.brancos + r.nulos
        assert r.comparecimento == int(dados["e"]["c"])


def test_resultado_zerado_do_segundo_turno_le_sem_votos():
    r = ler_resultado(carregar("ac-c0001-e006258-u.json"), ESQ, DIR)
    assert (r.esq, r.dir, r.comparecimento, r.secoes, r.aptos) == (0, 0, 0, 0, 0)


def test_resultado_sem_candidato_e_arquivo_inesperado():
    with pytest.raises(ArquivoInesperado):
        ler_resultado(carregar("ac-c0001-e006257-u.json"), ESQ, 99)
    with pytest.raises(ArquivoInesperado):
        ler_resultado({}, ESQ, DIR)


def test_resultado_do_brasil_no_primeiro_turno():
    r = ler_resultado(carregar("br-c0001-e006257-u.json"), ESQ, DIR)
    assert (r.esq, r.dir) == (53879538, 56104503)
    assert r.secoes == 499248
