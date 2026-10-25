"""Envia site/dados/projecao.json para a branch `dados` e pede um deploy do GitHub Pages.

A `main` fica só com código: o workflow do Pages copia o arquivo da branch `dados` antes de publicar. O push na
`dados` não dispara o workflow (ela não tem nenhum, e o ambiente github-pages só aceita a `main`), então cada push
é seguido de `gh workflow run pages.yml --ref main`.

O estado fica no git (o arquivo no worktree e origin/dados), então reiniciar no meio de um ciclo converge sem commit
repetido.
"""

import json
import logging
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from eleicao import config

log = logging.getLogger("eleicao.publicar")

BRANCH = "dados"
ARQUIVO = "projecao.json"


def _git(pasta: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=pasta, capture_output=True, text=True, check=check)


def _existe(pasta: Path, ref: str) -> bool:
    return _git(pasta, "rev-parse", "--verify", "--quiet", ref, check=False).returncode == 0


def preparar(repo: Path, pasta: Path) -> None:
    """Deixa em `pasta` um worktree da branch `dados`, criada a partir de origin ou do zero."""
    if (pasta / ".git").exists():
        return
    _git(repo, "worktree", "prune")
    _git(repo, "fetch", "origin", BRANCH, check=False)
    if _existe(repo, f"refs/heads/{BRANCH}"):
        _git(repo, "worktree", "add", str(pasta), BRANCH)
    elif _existe(repo, f"refs/remotes/origin/{BRANCH}"):
        _git(repo, "worktree", "add", "-b", BRANCH, str(pasta), f"origin/{BRANCH}")
    else:
        _git(repo, "worktree", "add", "--orphan", "-b", BRANCH, str(pasta))


def disparar_pages(repo: Path) -> None:
    subprocess.run(["gh", "workflow", "run", "pages.yml", "--ref", "main"], cwd=repo, capture_output=True, text=True, check=True)


@dataclass
class Publicador:
    fonte: Path
    pasta: Path
    disparar: Callable[[], None]
    pendente: bool = True
    """Há um push que o Pages ainda não publicou. Começa verdadeiro porque um disparo pode ter falhado antes do reinício."""

    def ciclo(self) -> None:
        """Falhas de git ou do gh sobem como CalledProcessError; o próximo ciclo retoma de onde parou."""
        if self.fonte.exists():
            novo = self.fonte.read_bytes()
            destino = self.pasta / ARQUIVO
            if not destino.exists() or destino.read_bytes() != novo:
                destino.write_bytes(novo)
            if _git(self.pasta, "status", "--porcelain", "--", ARQUIVO).stdout:
                doc = json.loads(novo)
                _git(self.pasta, "add", ARQUIVO)
                _git(self.pasta, "commit", "-q", "-m", f"projeção {doc['fase']} de {doc['atualizado']}")
        if self._a_frente():
            _git(self.pasta, "push", "-q", "origin", BRANCH)
            log.info("enviado %s", _git(self.pasta, "log", "-1", "--format=%s").stdout.strip())
            self.pendente = True
        if self.pendente:
            self.disparar()
            self.pendente = False

    def _a_frente(self) -> bool:
        if not _existe(self.pasta, "HEAD"):
            return False
        if not _existe(self.pasta, f"refs/remotes/origin/{BRANCH}"):
            return True
        return _git(self.pasta, "rev-list", "--count", f"origin/{BRANCH}..HEAD").stdout.strip() != "0"


def _mudou(fonte: Path) -> int | None:
    return fonte.stat().st_mtime_ns if fonte.exists() else None


def vigiar(publicador: Publicador, intervalo: float, dormir: Callable[[float], None] = time.sleep, voltas: int | None = None) -> None:
    """Publica assim que a projeção regrava o arquivo, sem esperar o intervalo. O intervalo só marca quando
    repetir um ciclo que falhou ou um disparo pendente, para não martelar o git e o gh a cada segundo."""
    visto, ultimo = None, -float("inf")
    while voltas is None or voltas > 0:
        marca = _mudou(publicador.fonte)
        if marca != visto or time.monotonic() - ultimo >= intervalo:
            visto, ultimo = marca, time.monotonic()
            try:
                publicador.ciclo()
            except subprocess.CalledProcessError as erro:
                log.warning("falhou, nova tentativa em %gs: %s", intervalo, (erro.stderr or "").strip())
        if voltas is not None:
            voltas -= 1
        dormir(1.0)


def rodar(intervalo: float) -> None:
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    pasta = config.DADOS / "publicacao"
    preparar(config.RAIZ, pasta)
    publicador = Publicador(config.SITE / "dados" / ARQUIVO, pasta, lambda: disparar_pages(config.RAIZ))
    try:
        vigiar(publicador, intervalo)
    except KeyboardInterrupt:
        log.info("encerrado")
