"""Gera site/dados/exemplo-metade.json: a apuração de 2026 simulada até a metade, com o modelo de verdade.

O 2º turno é inventado (`cenario_sintetico`: o voto do 1º turno de cada seção mais uma mudança conhecida),
as seções chegam na ordem real do 1º turno e cada ponto passa pelo mesmo `Modelo` e pela mesma `Saida`
do acompanhamento ao vivo. Rode da raiz do repositório depois de `uv run eleicao base`:

    uv run python scripts/gerar_exemplo_metade.py
"""

from datetime import datetime

from eleicao.config import BASES, SITE
from eleicao.ensaio import cenario_sintetico, gravar_exemplo
from eleicao.tipos import Base

SWING = 0.07

base = Base.ler(BASES / "2026")
cenario = cenario_sintetico(base, SWING, semente=11)
for pct, _, proj in gravar_exemplo(
    base, cenario, SITE / "dados" / "exemplo-metade.json",
    lambda hora: datetime.fromisoformat(str(hora)[:19]).replace(year=2026, month=10, day=25),
):
    f = proj.brasil.projecao
    print(f"{pct:5.1f}% apurado {proj.brasil.apurado:.2f} projeção {f.centro:.2f} [{f.baixo:.2f}, {f.alto:.2f}] chance {f.chance:.0f}%")

final = 100 * cenario["esq"].sum() / (cenario["esq"].sum() + cenario["dir"].sum())
print(f"resultado final do cenário inventado: {final:.2f}%")
