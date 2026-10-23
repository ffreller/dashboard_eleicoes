"""Deriva de site/dados/exemplo.json os JSONs fictícios de cada fase da apuração, para testar a página.

Gera exemplo-aguardando, exemplo-inicio, exemplo-vantagem e exemplo-encerrada em site/dados/.
Rode da raiz do repositório: uv run python scripts/gerar_exemplos_fases.py
"""

import copy
import json
from datetime import datetime, timedelta
from pathlib import Path

DADOS = Path("site/dados")
base = json.loads((DADOS / "exemplo.json").read_text(encoding="utf-8"))


def gravar(nome: str, doc: dict) -> None:
    (DADOS / f"exemplo-{nome}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(nome, len(doc["serie"]), "pontos")


def deslocar(faixa: dict | None, dp: float) -> dict | None:
    if faixa is None:
        return None
    return {k: round(v + dp, 2) for k, v in faixa.items()}


aguardando = copy.deepcopy(base)
aguardando.update(fase="aguardando", atualizado="2026-10-25T16:55:00-03:00", serie=[], ufs=[])
gravar("aguardando", aguardando)

inicio = copy.deepcopy(base)
t0 = datetime.fromisoformat(base["serie"][0]["hora"])
pontos = [(0.0, None), (0.12, 41.2), (0.31, 56.8), (0.58, 52.3), (0.83, 47.9)]
inicio["serie"] = [
    {
        "hora": (t0 + timedelta(seconds=30 * k)).isoformat(timespec="seconds"),
        "pct_secoes": pct,
        "pct_aptos": round(pct * 0.98, 2),
        "apurado": apurado,
        "votos_validos": int(118e6 * pct / 100),
        "projecao": None,
    }
    for k, (pct, apurado) in enumerate(pontos)
]
inicio["atualizado"] = inicio["serie"][-1]["hora"]
for i, u in enumerate(inicio["ufs"]):
    pct = 0.0 if i % 4 == 0 else round(0.9 * ((i * 7) % 10) / 10, 2)
    u.update(pct_secoes=pct, apurado=None if pct == 0 else u["apurado"], projecao=None)
gravar("inicio", inicio)

vantagem = copy.deepcopy(base)
vantagem["serie"] = [p for p in vantagem["serie"] if p["pct_secoes"] <= 55]
dp = 2.4
for p in vantagem["serie"]:
    if p["apurado"] is not None:
        p["apurado"] = round(p["apurado"] + dp, 2)
    p["projecao"] = deslocar(p["projecao"], dp)
vantagem["atualizado"] = vantagem["serie"][-1]["hora"]
for u in vantagem["ufs"]:
    u["pct_secoes"] = round(u["pct_secoes"] * 0.55, 2)
    u["apurado"] = round(u["apurado"] + dp, 2)
    u["projecao"] = deslocar(u["projecao"], dp)
gravar("vantagem", vantagem)

encerrada = copy.deepcopy(base)
ultimo = encerrada["serie"][-1]
final = 49.62
for k, pct in enumerate((99.4, 99.8, 100.0), start=1):
    hora = datetime.fromisoformat(ultimo["hora"]) + timedelta(minutes=3 * k)
    centro = final if pct == 100.0 else final + 0.03 * (3 - k)
    largura = 0.0 if pct == 100.0 else 0.12 / k
    encerrada["serie"].append({
        "hora": hora.isoformat(timespec="seconds"),
        "pct_secoes": pct,
        "pct_aptos": round(pct * 0.98, 2),
        "apurado": round(centro, 2),
        "votos_validos": int(118e6 * pct / 100),
        "projecao": {"centro": round(centro, 2), "baixo": round(centro - largura, 2), "alto": round(centro + largura, 2)},
    })
encerrada["fase"] = "encerrada"
encerrada["atualizado"] = encerrada["serie"][-1]["hora"]
for u in encerrada["ufs"]:
    c = u["projecao"]["centro"]
    u.update(pct_secoes=100.0, apurado=c, projecao={"centro": c, "baixo": c, "alto": c})
gravar("encerrada", encerrada)
