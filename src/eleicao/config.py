"""Códigos das eleições, candidatos e caminhos: a fonte única para o resto do pacote."""

from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
DADOS = RAIZ / "data"
BRUTOS = DADOS / "raw"
BASES = DADOS / "base"
SITE = RAIZ / "site"

UFS = (
    "ac", "al", "am", "ap", "ba", "ce", "df", "es", "go", "ma", "mg", "ms", "mt", "pa",
    "pb", "pe", "pi", "pr", "rj", "rn", "ro", "rr", "rs", "sc", "se", "sp", "to", "zz",
)

REGIAO = {
    "ac": "N", "am": "N", "ap": "N", "pa": "N", "ro": "N", "rr": "N", "to": "N",
    "al": "NE", "ba": "NE", "ce": "NE", "ma": "NE", "pb": "NE", "pe": "NE", "pi": "NE", "rn": "NE", "se": "NE",
    "df": "CO", "go": "CO", "ms": "CO", "mt": "CO",
    "es": "SE", "mg": "SE", "rj": "SE", "sp": "SE",
    "pr": "S", "rs": "S", "sc": "S",
    "zz": "EX",
}

CAPITAIS = frozenset({
    1392, 27855, 6050, 2550, 38490, 13897, 97012, 57053, 93734, 9210, 90670, 90514, 41238, 75353,
    20516, 4278, 25313, 12190, 60011, 17612, 88013, 35, 3018, 81051, 31054, 71072, 73440,
})
"""Códigos TSE dos municípios das capitais (campo "c" de mun-e006258-cm.json)."""


@dataclass(frozen=True)
class Candidato:
    chave: str
    nome: str
    numero: int
    partido: str


@dataclass(frozen=True)
class Divulgacao:
    """Endereços dos arquivos da divulgação de resultados do TSE para um turno presidencial."""

    ciclo: str
    eleicao: int
    pleito: int
    url_base: str = "https://resultados.tse.jus.br/oficial"
    cargo: int = 1

    def secoes(self, uf: str) -> str:
        return f"{self.url_base}/{self.ciclo}/arquivo-urna/{self.pleito}/config/{uf}/{uf}-p{self.pleito:06d}-cs.json"

    def andamento(self, uf: str) -> str:
        return f"{self.url_base}/{self.ciclo}/{self.eleicao}/dados/{uf}/{uf}-e{self.eleicao:06d}-ab.json"

    def resultado(self, uf: str, mun: int | None = None) -> str:
        """Resultado do cargo na UF (ou no Brasil, com uf="br") ou, com `mun`, no município."""
        local = uf if mun is None else f"{uf}{mun:05d}"
        return f"{self.url_base}/{self.ciclo}/{self.eleicao}/dados/{uf}/{local}-c{self.cargo:04d}-e{self.eleicao:06d}-u.json"


@dataclass(frozen=True)
class Eleicao:
    """Um 2º turno presidencial e as duas bases que explicam o voto em cada seção.

    Base A é o 1º turno do mesmo ano, nas mesmas seções, com os mesmos dois candidatos. Base B é o
    2º turno da eleição presidencial anterior, pareado por local de votação; `numeros_b` são os números
    de quem ocupou cada lado naquele 2º turno.
    """

    ano: int
    ano_b: int
    esquerda: Candidato
    direita: Candidato
    numeros_b: tuple[int, int]
    divulgacao: Divulgacao


ELEICOES = {
    2026: Eleicao(
        ano=2026,
        ano_b=2022,
        esquerda=Candidato("lula", "Lula", 13, "PT"),
        direita=Candidato("flavio", "Flávio Bolsonaro", 22, "PL"),
        numeros_b=(13, 22),
        divulgacao=Divulgacao(ciclo="ele2026", eleicao=6258, pleito=3221),
    ),
    # Ensaio: o 2º turno de 2022 reproduzido na ordem real de chegada dos boletins. O TSE não serve
    # mais esses arquivos; os códigos reais servem ao TSE falso (eleicao.tse.falso).
    2022: Eleicao(
        ano=2022,
        ano_b=2018,
        esquerda=Candidato("lula", "Lula", 13, "PT"),
        direita=Candidato("bolsonaro", "Jair Bolsonaro", 22, "PL"),
        numeros_b=(13, 17),
        divulgacao=Divulgacao(ciclo="ele2022", eleicao=545, pleito=407),
    ),
}
