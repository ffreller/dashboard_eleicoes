"""GET condicional, com tentativas e concorrência limitada, para a divulgação do TSE.

O cliente só guarda os validadores (ETag e Last-Modified) de cada endereço, não o corpo: quem chama
mantém o último arquivo lido e interpretado, e `igual` diz que ele continua valendo.
"""

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from typing import Literal

import httpx

log = logging.getLogger("eleicao.tse")

Situacao = Literal["novo", "igual", "ausente", "falhou"]


@dataclass(frozen=True)
class Baixa:
    situacao: Situacao
    corpo: bytes = b""


@dataclass
class Medidas:
    requisicoes: int = 0
    bytes: int = 0
    novos: int = 0
    iguais: int = 0
    ausentes: int = 0
    falhas: int = 0


class Cliente:
    def __init__(
        self,
        *,
        simultaneas: int = 16,
        por_segundo: float = 100.0,
        tentativas: int = 4,
        espera: float = 0.5,
        timeout: float = 20.0,
        transporte: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=10.0),
            limits=httpx.Limits(max_connections=simultaneas, max_keepalive_connections=simultaneas),
            headers={"User-Agent": "eleicao-2026/0.1"},
            follow_redirects=True,
            transport=transporte,
        )
        self._vaga = asyncio.Semaphore(simultaneas)
        self._tentativas = tentativas
        self._teto = por_segundo
        self._taxa = por_segundo
        self._ritmo = asyncio.Lock()
        self._proximo = 0.0
        self._pausa_ate = 0.0
        self._seguidas_429 = 0
        self._espera = espera
        self._validadores: dict[str, dict[str, str]] = {}
        self.medidas = Medidas()

    async def __aenter__(self) -> "Cliente":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._http.aclose()

    def esquecer(self, url: str) -> None:
        """Faz o próximo GET desse endereço trazer o corpo inteiro, em vez de um 304."""
        self._validadores.pop(url, None)

    def retirar_medidas(self) -> Medidas:
        medidas, self.medidas = self.medidas, Medidas()
        return medidas

    async def _esperar_vez(self) -> None:
        async with self._ritmo:
            agora = time.monotonic()
            largada = max(agora, self._proximo, self._pausa_ate)
            self._proximo = largada + 1 / self._taxa
        if largada > agora:
            await asyncio.sleep(largada - agora)

    def _limite_excedido(self, resposta: httpx.Response) -> None:
        """429 vem da borda da CDN e vale para todos os clientes: freia todas as requisições, não só a que falhou."""
        self._seguidas_429 += 1
        self._taxa = max(5.0, self._taxa / 2)
        try:
            pausa = float(resposta.headers["retry-after"])
        except (KeyError, ValueError):
            pausa = min(30.0, 0.5 * 2 ** self._seguidas_429)
        self._pausa_ate = max(self._pausa_ate, time.monotonic() + pausa)

    def _deu_certo(self) -> None:
        self._seguidas_429 = 0
        self._taxa = min(self._teto, self._taxa * 1.02)

    async def obter(self, url: str) -> Baixa:
        for tentativa in range(self._tentativas):
            if tentativa:
                # Jitter para que as 16 requisições que falharam juntas não voltem juntas.
                await asyncio.sleep(self._espera * 2 ** (tentativa - 1) * random.uniform(0.5, 1.5))
            await self._esperar_vez()
            try:
                async with self._vaga:
                    resposta = await self._http.get(url, headers=self._validadores.get(url))
            except httpx.TransportError as erro:
                self.medidas.requisicoes += 1
                log.debug("falha de rede em %s: %r", url, erro)
                continue
            self.medidas.requisicoes += 1
            self.medidas.bytes += resposta.num_bytes_downloaded
            status = resposta.status_code
            if status == 429:
                self._limite_excedido(resposta)
                continue
            if status < 500:
                self._deu_certo()
            if status == 200:
                self._guardar_validadores(url, resposta)
                self.medidas.novos += 1
                return Baixa("novo", resposta.content)
            if status == 304:
                self.medidas.iguais += 1
                return Baixa("igual")
            if status == 404:
                self.medidas.ausentes += 1
                return Baixa("ausente")
            log.debug("status %s em %s", status, url)
            if status < 500:
                break
        self.medidas.falhas += 1
        return Baixa("falhou")

    def _guardar_validadores(self, url: str, resposta: httpx.Response) -> None:
        validadores = {}
        if etag := resposta.headers.get("etag"):
            validadores["If-None-Match"] = etag
        if modificado := resposta.headers.get("last-modified"):
            validadores["If-Modified-Since"] = modificado
        if validadores:
            self._validadores[url] = validadores
        else:
            self._validadores.pop(url, None)
