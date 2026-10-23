"""Gera site/dados/exemplo-metade.json: a apuração de 2026 simulada até a metade, com o modelo de verdade.

O 2º turno é inventado (`cenario_sintetico`: o voto do 1º turno de cada seção mais uma mudança conhecida),
as seções chegam na ordem real do 1º turno e cada ponto passa pelo mesmo `Modelo` e pela mesma `Saida`
do acompanhamento ao vivo. Rode da raiz do repositório depois de `uv run eleicao base`:

    uv run python scripts/gerar_exemplo_metade.py
"""

import json
from datetime import datetime

import numpy as np

from eleicao.config import BASES, DADOS, ELEICOES, SITE
from eleicao.ensaio import apuracao_ate, cenario_sintetico, postos
from eleicao.modelo import Modelo
from eleicao.saida import Saida, ler_validacao
from eleicao.tipos import Base

SWING = 0.07
PONTOS = (0.1, 0.25, 0.5, 1, 1.5, 2, 3, 4, 5, 7, 10, 12.5, 15, 17.5, 20, 25, 30, 35, 40, 45, 50)

base = Base.ler(BASES / "2026")
cenario = cenario_sintetico(base, SWING, semente=11)
posto = postos(cenario, "real")
horas = np.sort(cenario["hora"].to_numpy())
modelo = Modelo(base)
destino = SITE / "dados" / "exemplo-metade.json"
destino.unlink(missing_ok=True)
saida = Saida(ELEICOES[2026], base, destino, ler_validacao(DADOS / "ensaio"))
for pct in PONTOS:
    limite = int(np.ceil(cenario.height * pct / 100))
    momento = datetime.fromisoformat(str(horas[limite - 1])[:19]).replace(year=2026, month=10, day=25)
    proj = modelo.projetar(apuracao_ate(base, cenario, posto, limite, momento))
    saida.registrar(proj, "apurando", momento)
    f = proj.brasil.projecao
    print(f"{pct:5.1f}% apurado {proj.brasil.apurado:.2f} projeção {f.centro:.2f} [{f.baixo:.2f}, {f.alto:.2f}] chance {f.chance:.0f}%")

doc = json.loads(destino.read_text(encoding="utf-8"))
doc["exemplo"] = True
destino.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
final = 100 * cenario["esq"].sum() / (cenario["esq"].sum() + cenario["dir"].sum())
print(f"resultado final do cenário inventado: {final:.2f}%")
