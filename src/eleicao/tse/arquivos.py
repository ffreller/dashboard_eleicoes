"""Leitura dos três arquivos da divulgação do TSE: seções (cs), andamento (ab) e resultado (u).

Cada leitor recebe o JSON já decodificado e devolve um registro pequeno e tipado. Os campos
numéricos do TSE chegam como texto; a conversão acontece aqui e só aqui.
"""

from dataclasses import dataclass
from datetime import datetime

import numpy as np

SEM_HORA = np.datetime64("NaT", "s")


class ArquivoInesperado(ValueError):
    """O JSON decodificou, mas não tem a forma que a divulgação promete."""


def _datahora(dia: str, hora: str) -> datetime | None:
    if not dia or not hora:
        return None
    d, m, a = dia.split("/")
    return datetime.fromisoformat(f"{a}-{m}-{d}T{hora}")


@dataclass(frozen=True)
class Secoes:
    """Seções principais de uma UF e quando cada uma foi totalizada, em colunas paralelas.

    Colunas em vez de uma lista de objetos porque o arquivo do estado de São Paulo passa de 100 mil
    seções e é relido a cada ciclo. `hora` é NaT enquanto a seção não foi totalizada.
    """

    uf: str
    mun: np.ndarray
    zona: np.ndarray
    secao: np.ndarray
    hora: np.ndarray

    @property
    def n_totalizadas(self) -> int:
        return int(np.count_nonzero(~np.isnat(self.hora)))


def ler_secoes(uf: str, dados: dict) -> Secoes:
    """Seções com `nsp` são agregadas à seção principal: não têm hora própria e ficam de fora."""
    mun, zona, secao, hora = [], [], [], []
    horas: dict[tuple[str, str], np.datetime64] = {}
    try:
        for municipio in dados["abr"][0]["mu"]:
            cod_mun = int(municipio["cd"])
            for z in municipio["zon"]:
                cod_zona = int(z["cd"])
                for s in z["sec"]:
                    if "nsp" in s:
                        continue
                    mun.append(cod_mun)
                    zona.append(cod_zona)
                    secao.append(int(s["ns"]))
                    chave = (s.get("da", ""), s.get("ha", ""))
                    if chave not in horas:
                        momento = _datahora(*chave)
                        horas[chave] = SEM_HORA if momento is None else np.datetime64(momento, "s")
                    hora.append(horas[chave])
    except (KeyError, IndexError, TypeError, ValueError) as erro:
        raise ArquivoInesperado(f"seções de {uf}: {erro!r}") from erro
    return Secoes(
        uf=uf,
        mun=np.array(mun, dtype=np.int32),
        zona=np.array(zona, dtype=np.int32),
        secao=np.array(secao, dtype=np.int32),
        hora=np.array(hora, dtype="datetime64[s]"),
    )


@dataclass(frozen=True)
class Andamento:
    """Uma linha do arquivo de andamento: quanto de um município já foi totalizado."""

    mun: int
    secoes_total: int
    secoes_totalizadas: int
    aptos_total: int
    aptos_totalizados: int
    atualizado: datetime | None

    @property
    def versao(self) -> tuple[int, datetime | None]:
        return self.secoes_totalizadas, self.atualizado


def ler_andamento(dados: dict) -> dict[int, Andamento]:
    """Andamento por município. O arquivo também traz uma linha da própria UF (ou uma por UF no Brasil)."""
    try:
        return {
            int(item["cdabr"]): Andamento(
                mun=int(item["cdabr"]),
                secoes_total=int(item["s"]["ts"]),
                secoes_totalizadas=int(item["s"]["st"]),
                aptos_total=int(item["e"]["te"]),
                aptos_totalizados=int(item["e"]["est"]),
                atualizado=_datahora(item["dt"], item["ht"]),
            )
            for item in dados["abr"]
            if item["tpabr"] == "mun"
        }
    except (KeyError, TypeError, ValueError) as erro:
        raise ArquivoInesperado(f"andamento: {erro!r}") from erro


@dataclass(frozen=True)
class Resultado:
    """Votos dos dois candidatos e totais do que já foi totalizado numa localidade."""

    esq: int
    dir: int
    brancos: int
    nulos: int
    comparecimento: int
    aptos: int
    secoes: int


def ler_resultado(dados: dict, numero_esq: int, numero_dir: int) -> Resultado:
    votos: dict[int, int] = {}
    try:
        for agrupamento in dados["carg"][0]["agr"]:
            for partido in agrupamento["par"]:
                for candidato in partido["cand"]:
                    votos[int(candidato["n"])] = int(candidato["vap"])
        return Resultado(
            esq=votos[numero_esq],
            dir=votos[numero_dir],
            brancos=int(dados["v"]["vb"]),
            nulos=int(dados["v"]["tvn"]),
            comparecimento=int(dados["v"]["tv"]),
            aptos=int(dados["e"]["est"]),
            secoes=int(dados["s"]["st"]),
        )
    except (KeyError, IndexError, TypeError, ValueError) as erro:
        raise ArquivoInesperado(f"resultado: {erro!r}") from erro
