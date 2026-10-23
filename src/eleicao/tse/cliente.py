"""GET condicional, com tentativas e concorrência limitada, para a divulgação do TSE.

O cliente só guarda os validadores (ETag e Last-Modified) de cada endereço, não o corpo: quem chama
mantém o último arquivo lido e interpretado, e `igual` diz que ele continua valendo.
"""

import asyncio
import logging
import random
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

    async def obter(self, url: str) -> Baixa:
        for tentativa in range(self._tentativas):
            if tentativa:
                # Jitter para que as 16 requisições que falharam juntas não voltem juntas.
                await asyncio.sleep(self._espera * 2 ** (tentativa - 1) * random.uniform(0.5, 1.5))
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
            if status != 429 and status < 500:
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
