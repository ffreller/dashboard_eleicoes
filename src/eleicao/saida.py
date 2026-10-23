"""Grava site/dados/projecao.json, o único arquivo que a página lê.

O formato está exemplificado em site/dados/exemplo.json (gerado por scripts/gerar_exemplo.py).
Percentuais são da esquerda sobre os votos válidos; a página mostra a direita como 100 − esquerda.
Reiniciar o processo no meio da apuração preserva a série já gravada.
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

import numpy as np

from eleicao.config import Eleicao
from eleicao.tipos import Base, Faixa, Projecao, Recorte

Fase = Literal["aguardando", "apurando", "encerrada"]

NOMES_UF = {
    "ac": "Acre", "al": "Alagoas", "am": "Amazonas", "ap": "Amapá", "ba": "Bahia", "ce": "Ceará",
    "df": "Distrito Federal", "es": "Espírito Santo", "go": "Goiás", "ma": "Maranhão", "mg": "Minas Gerais",
    "ms": "Mato Grosso do Sul", "mt": "Mato Grosso", "pa": "Pará", "pb": "Paraíba", "pe": "Pernambuco",
    "pi": "Piauí", "pr": "Paraná", "rj": "Rio de Janeiro", "rn": "Rio Grande do Norte", "ro": "Rondônia",
    "rr": "Roraima", "rs": "Rio Grande do Sul", "sc": "Santa Catarina", "se": "Sergipe", "sp": "São Paulo",
    "to": "Tocantins", "zz": "Exterior",
}

NIVEL_FAIXA = 95
PROJECAO_DESDE_PCT = 1.0


def _faixa(f: Faixa | None) -> dict | None:
    return None if f is None else {"centro": round(f.centro, 2), "baixo": round(f.baixo, 2), "alto": round(f.alto, 2)}


def _ponto(momento: datetime, r: Recorte) -> dict:
    return {
        "hora": momento.isoformat(timespec="seconds"),
        "pct_secoes": round(r.pct_secoes, 2),
        "pct_aptos": round(r.pct_aptos, 2),
        "apurado": None if r.apurado is None else round(r.apurado, 2),
        "votos_validos": r.votos_validos,
        "projecao": _faixa(r.projecao) if r.pct_secoes >= PROJECAO_DESDE_PCT else None,
    }


def _referencias_por_uf(base: Base) -> dict[str, tuple[float, float]]:
    """Por UF: % da esquerda entre os dois no 1º turno e no 2º turno anterior (ponderado pelos válidos)."""
    s = base.secoes
    uf = s["uf"].to_numpy()
    a_esq, a_dir, b_p = (s[c].to_numpy().astype(float) for c in ("a_esq", "a_dir", "b_p"))
    peso = a_esq + a_dir + s["a_outros"].to_numpy()
    refs = {}
    for u in np.unique(uf):
        m = uf == u
        dois = a_esq[m].sum() + a_dir[m].sum()
        refs[u] = (100 * a_esq[m].sum() / dois, 100 * np.average(b_p[m], weights=peso[m]))
    return refs


@dataclass
class Saida:
    eleicao: Eleicao
    base: Base
    caminho: Path
    validacao: dict | None = None
    serie: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._refs = _referencias_por_uf(self.base)
        if self.caminho.exists():
            antigo = json.loads(self.caminho.read_text(encoding="utf-8"))
            if antigo.get("eleicao", {}).get("ano") == self.eleicao.ano and not antigo.get("exemplo"):
                self.serie = antigo.get("serie", [])

    def registrar(self, projecao: Projecao | None, fase: Fase, agora: datetime) -> None:
        """Acrescenta um ponto quando a apuração andou e regrava o arquivo."""
        ufs = []
        if projecao is not None:
            ponto = _ponto(projecao.momento, projecao.brasil)
            ultimo = self.serie[-1] if self.serie else None
            if ultimo is None or (ultimo["pct_secoes"], ultimo["apurado"]) != (ponto["pct_secoes"], ponto["apurado"]):
                self.serie.append(ponto)
            elif ultimo["projecao"] != ponto["projecao"]:
                self.serie[-1] = ponto
            for uf, r in sorted(projecao.ufs.items()):
                primeiro, anterior = self._refs[uf]
                ufs.append({
                    "uf": uf.upper(),
                    "nome": NOMES_UF[uf],
                    "pct_secoes": round(r.pct_secoes, 2),
                    "apurado": None if r.apurado is None else round(r.apurado, 2),
                    "projecao": _faixa(r.projecao),
                    "primeiro_turno": round(primeiro, 2),
                    "segundo_turno_anterior": round(anterior, 2),
                })
        e = self.eleicao
        doc = {
            "versao": 1,
            "eleicao": {"ano": e.ano, "turno": 2, "cargo": "Presidente"},
            "candidatos": {
                lado: {"nome": c.nome, "numero": c.numero, "partido": c.partido}
                for lado, c in (("esq", e.esquerda), ("dir", e.direita))
            },
            "fase": fase,
            "atualizado": agora.isoformat(timespec="seconds"),
            "nivel_faixa": NIVEL_FAIXA,
            "projecao_desde_pct": PROJECAO_DESDE_PCT,
            "serie": self.serie,
            "ufs": ufs,
            "validacao": self.validacao,
        }
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.caminho.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, self.caminho)
