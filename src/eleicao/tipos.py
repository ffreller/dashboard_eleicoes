"""Formas de dados compartilhadas pela base, pelo cliente do TSE, pelo ensaio e pelo modelo.

O eixo de tudo é a seção principal (uma urna). Seções agregadas não existem aqui: seus votos e
eleitores já estão somados à seção principal, como o TSE faz na totalização. `Base` fixa a ordem das
seções e dos municípios; `Apuracao` descreve um instante da contagem nessa mesma ordem. O cliente ao
vivo e o ensaio produzem `Apuracao`; o modelo lê `Base` + `Apuracao` e devolve `Projecao`.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import polars as pl

COLUNAS_BASE = {
    "uf": pl.String,
    "mun": pl.Int32,
    "zona": pl.Int32,
    "secao": pl.Int32,
    "aptos": pl.Int32,
    "a_esq": pl.Int32,
    "a_dir": pl.Int32,
    "a_outros": pl.Int32,
    "a_brancos": pl.Int32,
    "a_nulos": pl.Int32,
    "a_comparecimento": pl.Int32,
    "a_hora": pl.Datetime,
    "b_p": pl.Float64,
    "b_nivel": pl.Int8,
}
"""Uma linha por seção principal do 2º turno a projetar.

`aptos` e `a_*` vêm do 1º turno do mesmo ano na mesma seção. `a_hora` é quando a seção entrou na
totalização do 1º turno (horário de Brasília). `b_p` é a fração de votos válidos da esquerda no 2º
turno anterior, medida na unidade pareada; `b_nivel` diz que unidade é essa (ver base.pareamento).
"""

COLUNAS_MUNICIPIOS = {
    "uf": pl.String,
    "mun": pl.Int32,
    "nome": pl.String,
    "capital": pl.Boolean,
}

COLUNAS_CENARIO = {
    "uf": pl.String,
    "mun": pl.Int32,
    "zona": pl.Int32,
    "secao": pl.Int32,
    "hora": pl.Datetime,
    "aptos": pl.Int32,
    "comparecimento": pl.Int32,
    "esq": pl.Int32,
    "dir": pl.Int32,
    "brancos": pl.Int32,
    "nulos": pl.Int32,
}
"""Resultado conhecido de um 2º turno, seção a seção, com a hora em que cada seção foi totalizada.

Alimenta o ensaio (que monta `Apuracao` direto do cenário) e o TSE falso (que serve o cenário nos
arquivos da divulgação). Só seções principais; `hora` nula significa seção nunca totalizada.
"""


def conferir_colunas(df: pl.DataFrame, esperado: dict) -> pl.DataFrame:
    """Falha se faltar coluna ou se o tipo divergir; devolve só as colunas do contrato, na ordem dele."""
    faltam = [c for c in esperado if c not in df.columns]
    if faltam:
        raise ValueError(f"colunas ausentes: {faltam}")
    errados = {c: (df.schema[c], t) for c, t in esperado.items() if not df.schema[c].is_(t) and t != pl.Datetime}
    if errados:
        raise TypeError(f"tipos divergentes (atual, esperado): {errados}")
    return df.select(list(esperado))


@dataclass(frozen=True)
class Base:
    secoes: pl.DataFrame
    municipios: pl.DataFrame
    mun_idx: np.ndarray
    """Para cada seção, a posição do seu município em `municipios`."""

    @classmethod
    def de_tabelas(cls, secoes: pl.DataFrame, municipios: pl.DataFrame) -> "Base":
        secoes = conferir_colunas(secoes, COLUNAS_BASE).sort("uf", "mun", "zona", "secao")
        municipios = conferir_colunas(municipios, COLUNAS_MUNICIPIOS).sort("uf", "mun")
        pos = municipios.with_row_index("i").select("uf", "mun", "i")
        idx = secoes.select("uf", "mun").join(pos, on=["uf", "mun"], how="left", maintain_order="left")["i"]
        if idx.null_count():
            raise ValueError(f"{idx.null_count()} seções sem município na tabela de municípios")
        return cls(secoes=secoes, municipios=municipios, mun_idx=idx.to_numpy().astype(np.int64))

    @classmethod
    def ler(cls, pasta: Path) -> "Base":
        return cls.de_tabelas(pl.read_parquet(pasta / "secoes.parquet"), pl.read_parquet(pasta / "municipios.parquet"))

    def gravar(self, pasta: Path) -> None:
        pasta.mkdir(parents=True, exist_ok=True)
        self.secoes.write_parquet(pasta / "secoes.parquet")
        self.municipios.write_parquet(pasta / "municipios.parquet")

    def col(self, nome: str) -> np.ndarray:
        return self.secoes[nome].to_numpy()

    @property
    def n_secoes(self) -> int:
        return self.secoes.height

    @property
    def n_municipios(self) -> int:
        return self.municipios.height


@dataclass(frozen=True)
class Apuracao:
    """O que já foi totalizado num instante, na ordem da `Base`.

    `totalizada` vem do arquivo de seções (seção com horário = totalizada). Os demais campos são por
    município (ordem de `Base.municipios`) e copiam o arquivo de resultado do município: votos, e
    `aptos` e `secoes` das seções totalizadas. Os dois arquivos são gerados em momentos diferentes e
    podem divergir; quem monta a `Apuracao` reporta os dois como vieram e o modelo reconcilia.
    """

    momento: datetime
    totalizada: np.ndarray
    esq: np.ndarray
    dir: np.ndarray
    brancos: np.ndarray
    nulos: np.ndarray
    comparecimento: np.ndarray
    aptos: np.ndarray
    secoes: np.ndarray


@dataclass(frozen=True)
class Faixa:
    """Projeção da esquerda em % dos votos válidos, com a faixa de incerteza e a chance (em %) de a
    esquerda terminar com mais da metade dos votos válidos, que é a fração dos cenários sorteados."""

    centro: float
    baixo: float
    alto: float
    chance: float


@dataclass(frozen=True)
class Recorte:
    """Brasil ou uma UF num instante."""

    pct_secoes: float
    pct_aptos: float
    apurado: float | None
    """% dos votos válidos da esquerda no que já foi totalizado (None sem votos)."""
    votos_validos: int
    projecao: Faixa | None


@dataclass(frozen=True)
class Projecao:
    momento: datetime
    brasil: Recorte
    ufs: dict[str, Recorte]
