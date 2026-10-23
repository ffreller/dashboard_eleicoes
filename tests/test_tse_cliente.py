import asyncio

import httpx

from eleicao.tse.apuracao import Estado
from eleicao.tse.arquivos import Andamento, Resultado
from eleicao.tse.cliente import Cliente

URL = "https://tse.test/a.json"


def obter(respostas: list[httpx.Response], n: int = 1, **opcoes):
    pedidos: list[httpx.Request] = []

    def atender(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(pedido)
        return respostas[min(len(pedidos), len(respostas)) - 1]

    async def ir():
        async with Cliente(transporte=httpx.MockTransport(atender), espera=0.001, por_segundo=1e6, **opcoes) as c:
            return [await c.obter(URL) for _ in range(n)], c.medidas

    baixas, medidas = asyncio.run(ir())
    return baixas, medidas, pedidos


def test_segundo_pedido_e_condicional_e_304_vira_igual():
    baixas, _, pedidos = obter(
        [httpx.Response(200, content=b"{}", headers={"etag": '"v1"', "last-modified": "Sun, 25 Oct 2026 20:00:00 GMT"}),
         httpx.Response(304)],
        n=2,
    )
    assert [b.situacao for b in baixas] == ["novo", "igual"]
    assert pedidos[1].headers["if-none-match"] == '"v1"'
    assert pedidos[1].headers["if-modified-since"] == "Sun, 25 Oct 2026 20:00:00 GMT"


def test_429_e_500_sao_repetidos_e_404_nao():
    baixas, medidas, pedidos = obter([httpx.Response(429), httpx.Response(500), httpx.Response(200, content=b"{}")])
    assert baixas[0].situacao == "novo" and len(pedidos) == 3

    baixas, _, pedidos = obter([httpx.Response(404)])
    assert baixas[0].situacao == "ausente" and len(pedidos) == 1


def test_esgotadas_as_tentativas_a_falha_e_contada():
    baixas, medidas, pedidos = obter([httpx.Response(503)], tentativas=3)
    assert baixas[0].situacao == "falhou" and len(pedidos) == 3 and medidas.falhas == 1


def andamento(st: int) -> Andamento:
    return Andamento(mun=1, secoes_total=10, secoes_totalizadas=st, aptos_total=100, aptos_totalizados=10 * st, atualizado=None)


def resultado(st: int) -> Resultado:
    return Resultado(esq=st, dir=st, brancos=0, nulos=0, comparecimento=2 * st, aptos=10 * st, secoes=st)


def test_resultado_que_anda_para_tras_so_entra_na_terceira_vez():
    estado = Estado()
    assert estado.aceitar_resultado("ac", 1, resultado(5), andamento(5))
    assert not estado.aceitar_resultado("ac", 1, resultado(3), andamento(5))
    assert not estado.aceitar_resultado("ac", 1, resultado(3), andamento(5))
    assert estado.resultados["ac", 1].secoes == 5
    assert estado.aceitar_resultado("ac", 1, resultado(3), andamento(5))
    assert estado.resultados["ac", 1].secoes == 3


def test_resultado_e_relido_quando_o_andamento_muda_ou_o_arquivo_ficou_para_tras():
    estado = Estado()
    assert not estado.precisa_resultado("ac", 1, andamento(0))
    assert estado.precisa_resultado("ac", 1, andamento(5))
    estado.aceitar_resultado("ac", 1, resultado(5), andamento(5))
    assert not estado.precisa_resultado("ac", 1, andamento(5))
    assert estado.precisa_resultado("ac", 1, andamento(6))
    estado.aceitar_resultado("ac", 1, resultado(5), andamento(6))
    assert estado.precisa_resultado("ac", 1, andamento(6))
