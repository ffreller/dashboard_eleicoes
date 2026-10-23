"""O que se sabe da apuração depois de ler os arquivos do TSE, e a `Apuracao` que o modelo consome."""

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import polars as pl

from eleicao.tipos import Apuracao, Base
from eleicao.tse.arquivos import Andamento, Resultado, Secoes

RECUSAS_ATE_ACEITAR = 3
"""Quantas leituras seguidas que andam para trás se recusam antes de aceitar que o TSE corrigiu para baixo."""


@dataclass
class Estado:
    """Último conteúdo bom de cada arquivo. Um arquivo novo só entra inteiro e só se não andar para trás."""

    secoes: dict[str, Secoes] = field(default_factory=dict)
    andamento: dict[str, dict[int, Andamento]] = field(default_factory=dict)
    resultados: dict[tuple[str, int], Resultado] = field(default_factory=dict)
    lidos: dict[tuple[str, int], Andamento] = field(default_factory=dict)
    """Linha do andamento vigente quando o resultado de cada município foi lido."""
    _recusas: dict[object, int] = field(default_factory=dict)

    def _aceitar(self, chave: object, anda_para_tras: bool) -> bool:
        if not anda_para_tras:
            self._recusas.pop(chave, None)
            return True
        recusas = self._recusas.get(chave, 0) + 1
        if recusas >= RECUSAS_ATE_ACEITAR:
            self._recusas.pop(chave)
            return True
        self._recusas[chave] = recusas
        return False

    def aceitar_secoes(self, novo: Secoes) -> bool:
        atual = self.secoes.get(novo.uf)
        if not self._aceitar(("cs", novo.uf), atual is not None and novo.n_totalizadas < atual.n_totalizadas):
            return False
        self.secoes[novo.uf] = novo
        return True

    def aceitar_andamento(self, uf: str, novo: dict[int, Andamento]) -> bool:
        atual = self.andamento.get(uf)
        anda_para_tras = atual is not None and _totalizadas(novo) < _totalizadas(atual)
        if not self._aceitar(("ab", uf), anda_para_tras):
            return False
        self.andamento[uf] = novo
        return True

    def aceitar_resultado(self, uf: str, mun: int, novo: Resultado, andamento: Andamento) -> bool:
        atual = self.resultados.get((uf, mun))
        anda_para_tras = atual is not None and (
            novo.secoes < atual.secoes or novo.comparecimento < atual.comparecimento
        )
        if not self._aceitar(("u", uf, mun), anda_para_tras):
            return False
        self.resultados[uf, mun] = novo
        self.lidos[uf, mun] = andamento
        return True

    def precisa_resultado(self, uf: str, mun: int, andamento: Andamento) -> bool:
        """Município com seção totalizada cujo resultado nunca foi lido, mudou no andamento ou ficou para trás."""
        if andamento.secoes_totalizadas == 0:
            return False
        lido = self.lidos.get((uf, mun))
        if lido is None:
            return True
        return lido.versao != andamento.versao or self.resultados[uf, mun].secoes < andamento.secoes_totalizadas


def _totalizadas(andamento: dict[int, Andamento]) -> int:
    return sum(a.secoes_totalizadas for a in andamento.values())


@dataclass(frozen=True)
class Montagem:
    apuracao: Apuracao
    secoes_fora_da_base: int
    municipios_fora_da_base: int


def montar(base: Base, estado: Estado, agora: datetime) -> Montagem:
    """Alinha o estado à Base. Os dois arquivos são reportados como vieram; quem reconcilia é o modelo.

    `momento` é a hora da última seção totalizada (ou `agora` se nenhuma), de modo que o mesmo código
    serve ao TSE real e ao falso, que roda com o relógio acelerado.
    """
    chaves = ["uf", "mun", "zona", "secao"]
    if estado.secoes:
        cs = pl.concat([
            pl.DataFrame({
                "uf": pl.Series([s.uf] * len(s.secao), dtype=pl.String),
                "mun": s.mun, "zona": s.zona, "secao": s.secao, "totalizada": ~np.isnat(s.hora),
            })
            for s in estado.secoes.values()
        ]).unique(subset=chaves, keep="first")
    else:
        cs = pl.DataFrame(schema={"uf": pl.String, "mun": pl.Int32, "zona": pl.Int32, "secao": pl.Int32, "totalizada": pl.Boolean})
    base_chaves = base.secoes.select(chaves)
    totalizada = (
        base_chaves.join(cs, on=chaves, how="left", maintain_order="left")["totalizada"].fill_null(False).to_numpy()
    )

    municipios = list(zip(base.municipios["uf"], base.municipios["mun"], strict=True))
    conhecidos = set(municipios)
    campos = {nome: np.zeros(len(municipios), dtype=np.int64) for nome in
              ("esq", "dir", "brancos", "nulos", "comparecimento", "aptos", "secoes")}
    for i, chave in enumerate(municipios):
        if (r := estado.resultados.get(chave)) is not None:
            for nome, valor in campos.items():
                valor[i] = getattr(r, nome)

    horas = [s.hora[~np.isnat(s.hora)] for s in estado.secoes.values()]
    horas = [h.max() for h in horas if h.size]
    momento = max(horas).item() if horas else agora

    return Montagem(
        apuracao=Apuracao(momento=momento, totalizada=totalizada, **campos),
        secoes_fora_da_base=cs.join(base_chaves, on=chaves, how="anti").height,
        municipios_fora_da_base=sum(1 for chave in estado.resultados if chave not in conhecidos),
    )
