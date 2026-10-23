"""Acompanha a divulgação do TSE: lê os arquivos, monta a `Apuracao`, projeta e grava o JSON da página."""

import asyncio
import dataclasses
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

from eleicao import config
from eleicao.config import UFS, Divulgacao, Eleicao
from eleicao.saida import Fase, Saida, ler_validacao
from eleicao.tipos import Apuracao, Base, Projecao
from eleicao.tse.apuracao import Estado, Montagem, montar
from eleicao.tse.arquivos import (
    Andamento,
    ArquivoInesperado,
    ler_andamento,
    ler_resultado,
    ler_secoes,
)
from eleicao.tse.cliente import Baixa, Cliente, Medidas

log = logging.getLogger("eleicao.tse")

BRASILIA = ZoneInfo("America/Sao_Paulo")


class Projetor(Protocol):
    def projetar(self, ap: Apuracao) -> Projecao: ...


@dataclass
class Resumo:
    invalidos: int = 0
    recusados: int = 0


async def ciclo(cliente: Cliente, div: Divulgacao, eleicao: Eleicao, estado: Estado) -> Resumo:
    """Atualiza `estado` com o que mudou no TSE. Falha de um arquivo mantém a cópia anterior dele."""
    resumo = Resumo()
    numeros = eleicao.esquerda.numero, eleicao.direita.numero

    def interpretar(url: str, baixa: Baixa, ler, aceitar) -> None:
        if baixa.situacao != "novo":
            return
        try:
            novo = ler(json.loads(baixa.corpo))
        except (ValueError, ArquivoInesperado) as erro:
            log.warning("arquivo ilegível, mantida a cópia anterior: %s (%s)", url, erro)
            resumo.invalidos += 1
            cliente.esquecer(url)
            return
        if not aceitar(novo):
            log.warning("arquivo anda para trás, mantida a cópia anterior: %s", url)
            resumo.recusados += 1
            cliente.esquecer(url)

    async def secoes(uf: str) -> None:
        url = div.secoes(uf)
        interpretar(url, await cliente.obter(url), lambda d: ler_secoes(uf, d), estado.aceitar_secoes)

    async def resultado(uf: str, mun: int, andamento: Andamento) -> None:
        url = div.resultado(uf, mun)
        baixa = await cliente.obter(url)
        if baixa.situacao == "igual" and (uf, mun) in estado.resultados:
            estado.lidos[uf, mun] = andamento
        interpretar(
            url, baixa, lambda d: ler_resultado(d, *numeros),
            lambda r: estado.aceitar_resultado(uf, mun, r, andamento),
        )

    async def andamento_e_resultados(uf: str) -> None:
        url = div.andamento(uf)
        interpretar(url, await cliente.obter(url), ler_andamento, lambda a: estado.aceitar_andamento(uf, a))
        pendentes = [
            resultado(uf, mun, a)
            for mun, a in estado.andamento.get(uf, {}).items()
            if estado.precisa_resultado(uf, mun, a)
        ]
        await asyncio.gather(*pendentes)

    await asyncio.gather(*(secoes(uf) for uf in UFS), *(andamento_e_resultados(uf) for uf in UFS))
    return resumo


def fase_da_contagem(ap: Apuracao, estado: Estado) -> Fase:
    """Encerrada quando toda seção da Base tem hora ou quando andamento e resultados dizem 100%.

    A segunda via existe porque o arquivo de seções pode deixar sem hora seções que o TSE já contou:
    no 1º turno, 41 seções do exterior ficaram assim e `st == ts` mesmo assim.
    """
    if not ap.totalizada.any() and not ap.secoes.any():
        return "aguardando"
    linhas = [a for uf in estado.andamento.values() for a in uf.values()]
    completo = (
        len(estado.andamento) == len(UFS)
        and all(a.secoes_totalizadas == a.secoes_total for a in linhas)
        and ap.secoes.sum() == sum(a.secoes_total for a in linhas)
    )
    return "encerrada" if ap.totalizada.all() or completo else "apurando"


def _linha(ap: Apuracao, fase: Fase, m: Medidas, resumo: Resumo, montagem: Montagem, segundos: float) -> str:
    validos = ap.esq.sum() + ap.dir.sum()
    esq = f"{100 * ap.esq.sum() / validos:.2f}%" if validos else "-"
    extra = ""
    if montagem.secoes_fora_da_base or montagem.municipios_fora_da_base:
        extra += f" | fora da base: {montagem.secoes_fora_da_base} seções, {montagem.municipios_fora_da_base} municípios"
    if resumo.invalidos or resumo.recusados:
        extra += f" | ilegíveis {resumo.invalidos}, recusados {resumo.recusados}"
    return (
        f"{ap.momento:%H:%M:%S} {fase} | seções {100 * ap.totalizada.mean():.2f}% | esq {esq} | "
        f"{m.requisicoes} req ({m.novos} novos, {m.iguais} iguais, {m.ausentes} ausentes, {m.falhas} falhas) "
        f"{m.bytes / 1e6:.1f} MB | {segundos:.1f}s{extra}"
    )


def rodar(
    ano: int,
    intervalo: float,
    url_base: str | None = None,
    *,
    pasta: Path | None = None,
    destino: Path | None = None,
    ciclos: int | None = None,
    modelo: Callable[[Base], Projetor] | None = None,
    por_segundo: float = 100.0,
) -> None:
    """`pasta` e `destino` trocam a Base e o JSON da página; `ciclos` limita as repetições (None é sem fim).

    `modelo` constrói o projetor a partir da Base; por padrão `eleicao.modelo.Modelo`. `por_segundo` limita as
    requisições à origem.
    """
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    eleicao = config.ELEICOES[ano]
    div = eleicao.divulgacao if url_base is None else dataclasses.replace(eleicao.divulgacao, url_base=url_base)
    base = Base.ler(pasta or config.BASES / str(ano))
    if modelo is None:
        from eleicao.modelo import Modelo as modelo
    saida = Saida(eleicao, base, destino or config.SITE / "dados" / "projecao.json", ler_validacao(config.DADOS / "ensaio"), div.resultado("br"))
    try:
        asyncio.run(_laco(eleicao, div, base, modelo(base), saida, intervalo, ciclos, por_segundo))
    except KeyboardInterrupt:
        log.info("encerrado")


async def _laco(
    eleicao: Eleicao, div: Divulgacao, base: Base, modelo: Projetor, saida: Saida, intervalo: float,
    ciclos: int | None, por_segundo: float,
) -> None:
    estado = Estado()
    feitos = 0
    async with Cliente(por_segundo=por_segundo) as cliente:
        while True:
            inicio = time.monotonic()
            agora = datetime.now(BRASILIA).replace(tzinfo=None)
            try:
                resumo = await ciclo(cliente, div, eleicao, estado)
                montagem = montar(base, estado, agora)
                ap = montagem.apuracao
                fase = fase_da_contagem(ap, estado)
                projecao = None if fase == "aguardando" else modelo.projetar(ap)
                saida.registrar(projecao, fase, agora)
                log.info(_linha(ap, fase, cliente.retirar_medidas(), resumo, montagem, time.monotonic() - inicio))
            except Exception:
                log.exception("ciclo falhou, tentando de novo no próximo")
            feitos += 1
            if ciclos is not None and feitos >= ciclos:
                return
            await asyncio.sleep(max(0.0, intervalo - (time.monotonic() - inicio)))
