"""Baixa os arquivos reais do TSE usados como fixture: o AC inteiro do 1º turno e o 2º turno zerado."""

import json
from dataclasses import replace
from pathlib import Path

import httpx

from eleicao.config import ELEICOES

PASTA = Path(__file__).parent
PRIMEIRO_TURNO = replace(ELEICOES[2026].divulgacao, eleicao=6257, pleito=3220)
SEGUNDO_TURNO = ELEICOES[2026].divulgacao


def baixar(http: httpx.Client, url: str, nome: str) -> bytes:
    r = http.get(url)
    r.raise_for_status()
    (PASTA / nome).write_bytes(r.content)
    return r.content


with httpx.Client(timeout=30) as http:
    baixar(http, PRIMEIRO_TURNO.secoes("ac"), "ac-p003220-cs.json")
    baixar(http, SEGUNDO_TURNO.secoes("ac"), "ac-p003221-cs.json")
    ab = json.loads(baixar(http, PRIMEIRO_TURNO.andamento("ac"), "ac-e006257-ab.json"))
    baixar(http, SEGUNDO_TURNO.andamento("ac"), "ac-e006258-ab.json")
    baixar(http, PRIMEIRO_TURNO.andamento("br"), "br-e006257-ab.json")
    baixar(http, PRIMEIRO_TURNO.resultado("ac"), "ac-c0001-e006257-u.json")
    baixar(http, PRIMEIRO_TURNO.resultado("br"), "br-c0001-e006257-u.json")
    baixar(http, SEGUNDO_TURNO.resultado("ac"), "ac-c0001-e006258-u.json")
    baixar(http, SEGUNDO_TURNO.resultado("br"), "br-c0001-e006258-u.json")
    for item in (i for i in ab["abr"] if i["tpabr"] == "mun"):
        mun = int(item["cdabr"])
        baixar(http, PRIMEIRO_TURNO.resultado("ac", mun), f"ac{mun:05d}-c0001-e006257-u.json")
