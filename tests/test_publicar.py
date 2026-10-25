import json
import subprocess

import pytest

from eleicao.publicar import Publicador, preparar


def git(pasta, *args):
    return subprocess.run(["git", *args], cwd=pasta, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for k in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(k, "teste")
    for k in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(k, "teste@exemplo")
    origem = tmp_path / "origem.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origem))
    repo = tmp_path / "repo"
    git(tmp_path, "clone", "-q", str(origem), str(repo))
    (repo / "README.md").write_text("código\n")
    git(repo, "add", "README.md")
    git(repo, "commit", "-q", "-m", "inicial")
    git(repo, "push", "-q", "origin", "main")
    return repo


class Disparos:
    def __init__(self):
        self.n = 0

    def __call__(self):
        self.n += 1


def gravar(arq, atualizado):
    arq.write_text(json.dumps({"fase": "apurando", "atualizado": atualizado}))


def publicado(repo):
    return json.loads(git(repo.parent / "origem.git", "show", "dados:projecao.json"))["atualizado"]


def test_publica_na_branch_dados_sem_tocar_a_main(repo, tmp_path):
    fonte = tmp_path / "projecao.json"
    gravar(fonte, "18:00")
    preparar(repo, repo / "pub")
    disparos = Disparos()
    Publicador(fonte, repo / "pub", disparos).ciclo()
    assert publicado(repo) == "18:00"
    assert disparos.n == 1
    assert git(repo.parent / "origem.git", "ls-tree", "--name-only", "main") == "README.md"


def test_ciclo_sem_mudanca_nao_faz_nada(repo, tmp_path):
    fonte = tmp_path / "projecao.json"
    gravar(fonte, "18:00")
    preparar(repo, repo / "pub")
    disparos = Disparos()
    pub = Publicador(fonte, repo / "pub", disparos)
    pub.ciclo()
    pub.ciclo()
    assert git(repo / "pub", "rev-list", "--count", "HEAD") == "1"
    assert disparos.n == 1


def test_reiniciar_nao_repete_commit(repo, tmp_path):
    fonte = tmp_path / "projecao.json"
    gravar(fonte, "18:00")
    preparar(repo, repo / "pub")
    Publicador(fonte, repo / "pub", Disparos()).ciclo()
    preparar(repo, repo / "pub")
    Publicador(fonte, repo / "pub", Disparos()).ciclo()
    assert git(repo / "pub", "rev-list", "--count", "HEAD") == "1"


def test_push_que_falha_e_retomado_no_ciclo_seguinte(repo, tmp_path):
    fonte = tmp_path / "projecao.json"
    gravar(fonte, "18:00")
    preparar(repo, repo / "pub")
    disparos = Disparos()
    pub = Publicador(fonte, repo / "pub", disparos)
    pub.ciclo()
    origem = git(repo, "remote", "get-url", "origin")
    git(repo, "remote", "set-url", "origin", str(tmp_path / "fora-do-ar.git"))
    gravar(fonte, "18:01")
    with pytest.raises(subprocess.CalledProcessError):
        pub.ciclo()
    git(repo, "remote", "set-url", "origin", origem)
    pub.ciclo()
    assert publicado(repo) == "18:01"
    assert disparos.n == 2


def test_disparo_que_falha_e_repetido(repo, tmp_path):
    fonte = tmp_path / "projecao.json"
    gravar(fonte, "18:00")
    preparar(repo, repo / "pub")
    tentativas = []

    def disparar():
        tentativas.append(1)
        if len(tentativas) == 1:
            raise subprocess.CalledProcessError(1, "gh")

    pub = Publicador(fonte, repo / "pub", disparar)
    with pytest.raises(subprocess.CalledProcessError):
        pub.ciclo()
    pub.ciclo()
    pub.ciclo()
    assert len(tentativas) == 2


def test_aproveita_a_branch_dados_que_ja_existe_no_origin(repo, tmp_path):
    fonte = tmp_path / "projecao.json"
    gravar(fonte, "18:00")
    preparar(repo, repo / "pub")
    Publicador(fonte, repo / "pub", Disparos()).ciclo()
    outro = tmp_path / "outro"
    git(tmp_path, "clone", "-q", str(repo.parent / "origem.git"), str(outro))
    preparar(outro, outro / "pub")
    gravar(fonte, "18:01")
    Publicador(fonte, outro / "pub", Disparos()).ciclo()
    assert publicado(repo) == "18:01"
    assert git(outro / "pub", "rev-list", "--count", "HEAD") == "2"


def test_vigiar_publica_assim_que_o_arquivo_muda(repo, tmp_path):
    from eleicao.publicar import vigiar

    fonte = tmp_path / "projecao.json"
    gravar(fonte, "18:00")
    preparar(repo, repo / "pub")
    pub = Publicador(fonte, repo / "pub", Disparos())
    horas = iter(["18:00:30", "18:01", "18:01"])

    def dormir(_):
        gravar(fonte, next(horas))

    vigiar(pub, intervalo=3600, dormir=dormir, voltas=3)
    assert publicado(repo) == "18:01"
    assert git(repo / "pub", "rev-list", "--count", "HEAD") == "3"


def test_vigiar_sem_mudanca_espera_o_intervalo(repo, tmp_path):
    from eleicao.publicar import vigiar

    fonte = tmp_path / "projecao.json"
    gravar(fonte, "18:00")
    preparar(repo, repo / "pub")
    ciclos = []
    pub = Publicador(fonte, repo / "pub", Disparos())
    pub.ciclo = lambda: ciclos.append(1)
    vigiar(pub, intervalo=3600, dormir=lambda _: None, voltas=5)
    assert len(ciclos) == 1
