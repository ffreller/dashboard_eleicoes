"""TSE falso: serve um cenário de 2º turno nos mesmos arquivos e caminhos da divulgação real.

O relógio simulado começa um minuto antes da primeira seção e anda `velocidade` vezes mais rápido que o
real. Uma seção entra nos arquivos quando o relógio passa da sua `hora`. Em marcha, o relógio só avança
de `passo` em `passo` segundos simulados, como a divulgação, que republica em lotes.
"""

import json
import logging
import random
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from email.utils import formatdate, parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import polars as pl

from eleicao import config
from eleicao.config import UFS, Divulgacao
from eleicao.saida import NOMES_UF
from eleicao.tipos import COLUNAS_CENARIO, COLUNAS_MUNICIPIOS, conferir_colunas

log = logging.getLogger("eleicao.tse")

EPOCA = np.datetime64("1970-01-01T00:00:00", "s")
NUNCA = np.iinfo(np.int64).max


@dataclass
class Falhas:
    """Defeitos injetados, sorteados por requisição. `atraso_resultado` faz o resultado ficar um passo atrás das seções."""

    p_404: float = 0.03
    p_500: float = 0.03
    p_truncado: float = 0.02
    atraso_resultado: bool = True
    semente: int = 0


class Relogio:
    def __init__(self, inicio: datetime, velocidade: float) -> None:
        self._inicio = np.datetime64(inicio, "s").astype(np.int64)
        self._velocidade = velocidade
        self._largada = time.monotonic()
        self.fixo: int | None = None

    def fixar(self, momento: datetime | None) -> None:
        self.fixo = None if momento is None else int(np.datetime64(momento, "s").astype(np.int64))

    def segundos(self, passo: int) -> int:
        if self.fixo is not None:
            return self.fixo
        simulado = self._inicio + (time.monotonic() - self._largada) * self._velocidade
        return int(simulado // passo * passo)


@dataclass(frozen=True)
class Soma:
    """Totais de seções e votos por unidade (município, UF ou Brasil), na ordem das unidades."""

    st: np.ndarray
    est: np.ndarray
    c: np.ndarray
    esq: np.ndarray
    dir: np.ndarray
    brancos: np.ndarray
    nulos: np.ndarray
    ultima: np.ndarray
    """Maior hora, em segundos desde 1970, entre as seções somadas (0 se nenhuma)."""


@dataclass(frozen=True)
class Foto:
    """A contagem num instante: quantas seções entraram e o que elas somam."""

    n: int
    mun: Soma
    uf: Soma
    br: Soma


class Cenario:
    def __init__(self, tabela: pl.DataFrame, municipios: pl.DataFrame) -> None:
        tabela = conferir_colunas(tabela, COLUNAS_CENARIO)
        tabela = tabela.sort("uf", "mun", "zona", "secao")
        if not tabela["hora"].drop_nulls().len():
            raise ValueError("cenário sem nenhuma hora de totalização")
        desconhecidas = set(tabela["uf"]) - set(UFS)
        if desconhecidas:
            raise ValueError(f"UFs fora da lista: {sorted(desconhecidas)}")
        nomes = conferir_colunas(municipios, COLUNAS_MUNICIPIOS)
        self.nomes = {(u, m): n for u, m, n in nomes.select("uf", "mun", "nome").iter_rows()}

        self.uf = tabela["uf"].to_list()
        self.mun = tabela["mun"].to_numpy()
        self.zona = tabela["zona"].to_numpy()
        self.secao = tabela["secao"].to_numpy()
        hora = tabela["hora"].cast(pl.Datetime("ms")).to_numpy().astype("datetime64[s]")
        self.hora = np.where(np.isnat(hora), NUNCA, (hora - EPOCA).astype(np.int64))
        self.hora_ordenada = np.sort(self.hora)
        self.valores = {c: tabela[c].to_numpy().astype(np.int64) for c in
                        ("aptos", "comparecimento", "esq", "dir", "brancos", "nulos")}

        uf_idx = np.array([UFS.index(u) for u in self.uf])
        chave = uf_idx * 10**6 + self.mun
        self.unidades_mun, self.mun_do_secao = np.unique(chave, return_inverse=True)
        self.mun_inicio = np.flatnonzero(np.diff(self.mun_do_secao, prepend=-1))
        self.uf_do_mun = self.unidades_mun // 10**6
        self.ufs_presentes = np.unique(self.uf_do_mun)
        self.uf_inicio = np.flatnonzero(np.diff(self.uf_do_mun, prepend=-1))
        self.uf_pos = np.searchsorted(self.ufs_presentes, self.uf_do_mun)
        self.secoes_da_uf = {
            UFS[u]: slice(i, j)
            for u, i, j in zip(
                self.ufs_presentes, np.searchsorted(uf_idx, self.ufs_presentes), np.searchsorted(uf_idx, self.ufs_presentes, side="right"),
                strict=True,
            )
        }
        self.total = self._somar(np.ones(len(self.hora), dtype=bool))

        self.primeira_hora = _datahora(int(self.hora_ordenada[0]))
        self.texto_hora = {h: _texto_hora(int(h)) for h in np.unique(self.hora[self.hora != NUNCA])}

    def _somar(self, mask: np.ndarray) -> tuple[Soma, Soma, Soma]:
        n_mun = len(self.unidades_mun)
        n_uf = len(self.ufs_presentes)

        def por_mun(x: np.ndarray) -> np.ndarray:
            return np.rint(np.bincount(self.mun_do_secao, weights=np.where(mask, x, 0), minlength=n_mun)).astype(np.int64)

        mun = {
            "st": por_mun(np.ones(len(mask))), "est": por_mun(self.valores["aptos"]), "c": por_mun(self.valores["comparecimento"]),
            **{k: por_mun(self.valores[k]) for k in ("esq", "dir", "brancos", "nulos")},
        }
        mun["ultima"] = np.maximum.reduceat(np.where(mask, self.hora, 0), self.mun_inicio)
        uf = {k: np.rint(np.bincount(self.uf_pos, weights=v, minlength=n_uf)).astype(np.int64) for k, v in mun.items() if k != "ultima"}
        uf["ultima"] = np.maximum.reduceat(mun["ultima"], self.uf_inicio)
        br = {k: v.sum(keepdims=True) for k, v in mun.items() if k != "ultima"}
        br["ultima"] = mun["ultima"].max(keepdims=True)
        return Soma(**mun), Soma(**uf), Soma(**br)

    def foto(self, segundos: int) -> Foto:
        n = int(np.searchsorted(self.hora_ordenada, segundos, side="right"))
        return Foto(n, *self._somar(self.hora <= segundos))


def _datahora(segundos: int) -> datetime:
    return datetime(1970, 1, 1) + timedelta(seconds=segundos)


def _texto_hora(segundos: int) -> tuple[str, str]:
    d = _datahora(segundos)
    return d.strftime("%d/%m/%Y"), d.strftime("%H:%M:%S")


def _pct(parte: int, todo: int) -> str:
    return f"{100 * parte / todo:.2f}".replace(".", ",") if todo else "0,00"


def _dt_ht(segundos: int) -> tuple[str, str]:
    return _texto_hora(segundos) if segundos else ("", "")


class Arquivos:
    """Gera o corpo de cada arquivo da divulgação para uma foto da contagem."""

    def __init__(self, cenario: Cenario, div: Divulgacao, esq: config.Candidato, dir: config.Candidato) -> None:
        self.c = cenario
        self.div = div
        self.candidatos = (esq, dir)
        self.rotas: dict[str, tuple[str, str, int | None]] = {}
        sem_base = replace(div, url_base="/oficial")
        for uf in UFS:
            self.rotas[sem_base.secoes(uf)] = ("cs", uf, None)
            self.rotas[sem_base.andamento(uf)] = ("ab", uf, None)
            self.rotas[sem_base.resultado(uf)] = ("u", uf, None)
        self.rotas[sem_base.andamento("br")] = ("ab", "br", None)
        self.rotas[sem_base.resultado("br")] = ("u", "br", None)
        for u, m in zip(cenario.uf_do_mun, cenario.unidades_mun % 10**6, strict=True):
            self.rotas[sem_base.resultado(UFS[u], int(m))] = ("u", UFS[u], int(m))

    def versao(self, rota: tuple[str, str, int | None], foto: Foto) -> int:
        """Quantas seções o arquivo cobre. O corpo muda só quando esse número muda."""
        _, uf, mun = rota
        if uf == "br":
            return foto.n
        if mun is not None:
            return int(foto.mun.st[self._pos_mun(uf, mun)])
        pos = self._pos_uf(uf)
        return 0 if pos is None else int(foto.uf.st[pos])

    def _pos_uf(self, uf: str) -> int | None:
        achado = np.flatnonzero(self.c.ufs_presentes == UFS.index(uf))
        return int(achado[0]) if achado.size else None

    def _pos_mun(self, uf: str, mun: int) -> int:
        return int(np.searchsorted(self.c.unidades_mun, UFS.index(uf) * 10**6 + mun))

    def corpo(self, rota: tuple[str, str, int | None], foto: Foto, agora: int) -> str:
        tipo, uf, mun = rota
        cabecalho = self._cabecalho(agora)
        if tipo == "cs":
            return self._secoes(uf, foto, cabecalho)
        if tipo == "ab":
            return self._andamento(uf, foto, cabecalho)
        return self._resultado(uf, mun, foto, cabecalho)

    def _cabecalho(self, agora: int) -> dict:
        dg, hg = _texto_hora(agora)
        return {"dg": dg, "hg": hg, "idg": str(agora)}

    def _secoes(self, uf: str, foto: Foto, cabecalho: dict) -> str:
        c = self.c
        zonas: dict[tuple[int, int], list[str]] = {}
        corte = c.secoes_da_uf.get(uf, slice(0, 0))
        limite = int(c.hora_ordenada[foto.n - 1]) if foto.n else -1
        for i in range(corte.start, corte.stop):
            h = int(c.hora[i])
            feita = h <= limite
            ns = f'{{"ns":"{c.secao[i]:04d}"'
            if feita:
                da, ha = c.texto_hora[h]
                ns += f',"da":"{da}","ha":"{ha}"'
            zonas.setdefault((int(c.mun[i]), int(c.zona[i])), []).append(ns + "}")
        por_mun: dict[int, list[str]] = {}
        for (mun, zona), secoes in zonas.items():
            por_mun.setdefault(mun, []).append(f'{{"cd":"{zona:04d}","sec":[{",".join(secoes)}]}}')
        municipios = ",".join(
            f'{{"cd":"{mun:05d}","nm":{json.dumps(c.nomes.get((uf, mun), str(mun)), ensure_ascii=False)},"zon":[{",".join(z)}]}}'
            for mun, z in por_mun.items()
        )
        corpo = {**cabecalho, "f": "o", "cdp": str(self.div.pleito)}
        return json.dumps(corpo)[:-1] + f',"abr":[{{"cd":"{uf}","ds":"{NOMES_UF[uf].upper()}","mu":[{municipios}]}}]}}'

    def _andamento(self, uf: str, foto: Foto, cabecalho: dict) -> str:
        c = self.c
        itens = []
        if uf == "br":
            for i, u in enumerate(c.ufs_presentes):
                itens.append(self._item_andamento("uf", UFS[u], foto.uf, c.total[1], i))
            itens.append(self._item_andamento("br", "br", foto.br, c.total[2], 0))
        else:
            for i, (u, m) in enumerate(zip(c.uf_do_mun, c.unidades_mun % 10**6, strict=True)):
                if UFS[u] == uf:
                    itens.append(self._item_andamento("mun", f"{m:05d}", foto.mun, c.total[0], i))
            pos = self._pos_uf(uf)
            if pos is not None:
                itens.append(self._item_andamento("uf", uf, foto.uf, c.total[1], pos))
        return json.dumps({"ele": str(self.div.eleicao), "t": "2", "f": "o", **cabecalho, "abr": itens}, ensure_ascii=False)

    def _item_andamento(self, tpabr: str, cd: str, s: Soma, total: Soma, i: int) -> dict:
        ts, st = int(total.st[i]), int(s.st[i])
        te, est, comp = int(total.est[i]), int(s.est[i]), int(s.c[i])
        dt, ht = _dt_ht(int(s.ultima[i]))
        return {
            "and": "n" if st == 0 else "f" if st == ts else "a", "tpabr": tpabr, "cdabr": cd, "dt": dt, "ht": ht,
            "s": {"ts": str(ts), "st": str(st), "pst": _pct(st, ts), "snt": str(ts - st), "psnt": _pct(ts - st, ts)},
            "e": {
                "te": str(te), "est": str(est), "pest": _pct(est, te), "esnt": str(te - est), "pesnt": _pct(te - est, te),
                "c": str(comp), "pc": _pct(comp, est), "a": str(est - comp), "pa": _pct(est - comp, est),
            },
        }

    def _resultado(self, uf: str, mun: int | None, foto: Foto, cabecalho: dict) -> str:
        c = self.c
        if uf == "br":
            soma, total, i, tpabr, cd = foto.br, c.total[2], 0, "br", "br"
        elif mun is not None:
            i = self._pos_mun(uf, mun)
            soma, total, tpabr, cd = foto.mun, c.total[0], "mun", f"{mun:05d}"
        else:
            i = self._pos_uf(uf)
            soma, total, tpabr, cd = foto.uf, c.total[1], "uf", uf
        if i is None:
            vazio = np.zeros(1, dtype=np.int64)
            soma = Soma(*([vazio] * 8))
            total = soma
            i = 0
        ts, st = int(total.st[i]), int(soma.st[i])
        te, est, comp = int(total.est[i]), int(soma.est[i]), int(soma.c[i])
        esq, dir_, brancos, nulos = (int(getattr(soma, k)[i]) for k in ("esq", "dir", "brancos", "nulos"))
        validos = esq + dir_
        dt, ht = _dt_ht(int(soma.ultima[i]))
        agrupamentos = [
            {
                "n": str(280001800000 + cand.numero), "nm": cand.partido, "tp": "i", "com": cand.partido,
                "par": [{
                    "n": str(cand.numero), "sg": cand.partido, "nm": cand.partido,
                    "cand": [{
                        "n": str(cand.numero), "nm": cand.nome, "nmu": cand.nome.upper(), "seq": str(k + 1),
                        "vap": str(v), "pvap": _pct(v, validos), "pvapn": _pct(v, validos),
                    }],
                }],
            }
            for k, (cand, v) in enumerate(zip(self.candidatos, (esq, dir_), strict=True))
        ]
        corpo = {
            "ele": str(self.div.eleicao), "t": "2", "f": "o", "sup": "n", "tpabr": tpabr, "cdabr": cd,
            **cabecalho, "dt": dt, "ht": ht, "dv": "s", "tf": "s" if st == ts else "n",
            "and": "n" if st == 0 else "f" if st == ts else "a",
            "carg": [{"cd": "1", "nmn": "Presidente", "nmm": "Presidente", "nmf": "Presidente", "nv": "1", "agr": agrupamentos}],
            "s": {"ts": str(ts), "st": str(st), "pst": _pct(st, ts), "snt": str(ts - st), "psnt": _pct(ts - st, ts)},
            "e": {
                "te": str(te), "est": str(est), "pest": _pct(est, te), "esnt": str(te - est), "pesnt": _pct(te - est, te),
                "c": str(comp), "pc": _pct(comp, est), "a": str(est - comp), "pa": _pct(est - comp, est),
            },
            "v": {
                "tv": str(comp), "vvc": str(validos), "vv": str(validos), "vnom": str(validos),
                "vb": str(brancos), "pvb": _pct(brancos, comp), "tvn": str(nulos), "ptvn": _pct(nulos, comp),
                "vn": str(nulos), "vnt": "0",
            },
        }
        return json.dumps(corpo, ensure_ascii=False)


@dataclass
class _Publicado:
    versao: int
    corpo: bytes
    etag: str
    modificado: float


class TseFalso:
    """Servidor HTTP do TSE falso. `relogio.fixar(...)` congela o tempo e `falhas = None` desliga os defeitos."""

    def __init__(
        self,
        ano: int,
        *,
        velocidade: float = 60.0,
        porta: int = 0,
        pasta: Path | None = None,
        falhas: Falhas | None = None,
        passo: int = 60,
    ) -> None:
        pasta = pasta or config.BASES / str(ano)
        eleicao = config.ELEICOES[ano]
        self.cenario = Cenario(pl.read_parquet(pasta / "cenario.parquet"), pl.read_parquet(pasta / "municipios.parquet"))
        self.arquivos = Arquivos(self.cenario, eleicao.divulgacao, eleicao.esquerda, eleicao.direita)
        self.passo = passo
        self.relogio = Relogio(self.cenario.primeira_hora - timedelta(minutes=1), velocidade)
        self.falhas = falhas
        self._sorteio = random.Random(falhas.semente if falhas else 0)
        self._trava = threading.Lock()
        self._fotos: dict[int, Foto] = {}
        self._publicados: dict[str, _Publicado] = {}
        self._http = ThreadingHTTPServer(("127.0.0.1", porta), self._handler())
        self._http.daemon_threads = True
        self._fio: threading.Thread | None = None

    @property
    def url_base(self) -> str:
        return f"http://localhost:{self._http.server_address[1]}/oficial"

    def __enter__(self) -> "TseFalso":
        self._fio = threading.Thread(target=self._http.serve_forever, daemon=True)
        self._fio.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._http.shutdown()
        self._http.server_close()

    def servir_para_sempre(self) -> None:
        try:
            self._http.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self._http.server_close()

    def _foto(self, segundos: int) -> Foto:
        n = int(np.searchsorted(self.cenario.hora_ordenada, segundos, side="right"))
        if n not in self._fotos:
            if len(self._fotos) > 8:
                self._fotos.clear()
            self._fotos[n] = self.cenario.foto(segundos)
        return self._fotos[n]

    def publicar(self, caminho: str) -> _Publicado | None:
        rota = self.arquivos.rotas.get(caminho)
        if rota is None:
            return None
        with self._trava:
            agora = self.relogio.segundos(self.passo)
            defasagem = self.passo if self.falhas and self.falhas.atraso_resultado and rota[0] == "u" else 0
            foto = self._foto(agora - defasagem)
            versao = self.arquivos.versao(rota, foto)
            atual = self._publicados.get(caminho)
            if atual is None or atual.versao != versao:
                corpo = self.arquivos.corpo(rota, foto, agora).encode("utf-8")
                atual = _Publicado(versao, corpo, f'"{versao}"', int(time.time()))
                self._publicados[caminho] = atual
            return atual

    def sortear_falha(self) -> str | None:
        f = self.falhas
        if f is None:
            return None
        with self._trava:
            x = self._sorteio.random()
        for nome, p in (("404", f.p_404), ("500", f.p_500), ("truncado", f.p_truncado)):
            if x < p:
                return nome
            x -= p
        return None

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        servidor = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_: object) -> None:
                pass

            def _responder(self, status: int, corpo: bytes = b"", extra: dict | None = None, enviar: int | None = None) -> None:
                self.send_response(status)
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                if status != 304:
                    self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                self.wfile.write(corpo if enviar is None else corpo[:enviar])
                if enviar is not None:
                    self.close_connection = True

            def do_GET(self) -> None:
                publicado = servidor.publicar(self.path.split("?")[0])
                if publicado is None:
                    return self._responder(404)
                falha = servidor.sortear_falha()
                if falha == "404":
                    return self._responder(404)
                if falha == "500":
                    return self._responder(500)
                cabecalhos = {
                    "ETag": publicado.etag,
                    "Last-Modified": formatdate(publicado.modificado, usegmt=True),
                    "Content-Type": "application/json",
                }
                if self._nao_modificado(publicado):
                    return self._responder(304, extra=cabecalhos)
                self._responder(200, publicado.corpo, cabecalhos, enviar=len(publicado.corpo) // 2 if falha == "truncado" else None)

            def _nao_modificado(self, publicado: _Publicado) -> bool:
                if (etag := self.headers.get("If-None-Match")) is not None:
                    return etag == publicado.etag
                if desde := self.headers.get("If-Modified-Since"):
                    return parsedate_to_datetime(desde).timestamp() >= publicado.modificado
                return False

        return Handler


def servir(ano: int, velocidade: float, porta: int, *, pasta: Path | None = None, falhas: Falhas | None = None) -> None:
    """Sobe o TSE falso e bloqueia. Aponte `eleicao ao-vivo --url-base` para o endereço impresso."""
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    servidor = TseFalso(ano, velocidade=velocidade, porta=porta, pasta=pasta, falhas=falhas)
    log.info("TSE falso em %s (velocidade %gx, relógio inicia %s)", servidor.url_base, velocidade, servidor.cenario.primeira_hora - timedelta(minutes=1))
    servidor.servir_para_sempre()
