"""Gera site/dados/exemplo.json: um JSON fictício no formato que o pipeline grava, para desenvolver a página."""

import json
import math
import random
from datetime import datetime, timedelta, timezone

BRT = timezone(timedelta(hours=-3))
UFS = {
    "AC": "Acre", "AL": "Alagoas", "AM": "Amazonas", "AP": "Amapá", "BA": "Bahia", "CE": "Ceará",
    "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão", "MG": "Minas Gerais",
    "MS": "Mato Grosso do Sul", "MT": "Mato Grosso", "PA": "Pará", "PB": "Paraíba", "PE": "Pernambuco",
    "PI": "Piauí", "PR": "Paraná", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte", "RO": "Rondônia",
    "RR": "Roraima", "RS": "Rio Grande do Sul", "SC": "Santa Catarina", "SE": "Sergipe", "SP": "São Paulo",
    "TO": "Tocantins", "ZZ": "Exterior",
}
PRIMEIRO = {
    "AC": 30, "AL": 58, "AM": 47, "AP": 45, "BA": 70, "CE": 66, "DF": 38, "ES": 40, "GO": 35, "MA": 69,
    "MG": 48, "MS": 36, "MT": 33, "PA": 53, "PB": 65, "PE": 65, "PI": 74, "PR": 35, "RJ": 42, "RN": 63,
    "RO": 29, "RR": 25, "RS": 41, "SC": 30, "SE": 66, "SP": 41, "TO": 47, "ZZ": 45,
}

random.seed(7)
final = 49.6
inicio = datetime(2026, 10, 25, 17, 0, tzinfo=BRT)
serie = []
for k in range(80):
    hora = inicio + timedelta(minutes=3 * k)
    pct = min(100.0, 100 * (1 - math.exp(-k / 18)))
    apurado = final - 5.5 * math.exp(-pct / 35) + random.uniform(-0.15, 0.15)
    largura = 0.25 + 3.0 / math.sqrt(1 + pct)
    proj = None
    if pct >= 1:
        c = final + random.uniform(-0.25, 0.25) * largura
        proj = {"centro": round(c, 2), "baixo": round(c - largura, 2), "alto": round(c + largura, 2)}
    serie.append({
        "hora": hora.isoformat(timespec="seconds"),
        "pct_secoes": round(pct, 2),
        "pct_aptos": round(pct * 0.98, 2),
        "apurado": round(apurado, 2) if pct > 0 else None,
        "votos_validos": int(118e6 * pct / 100),
        "projecao": proj,
    })
    if pct > 99.9:
        break

ufs = []
for uf, nome in UFS.items():
    pct = round(random.uniform(70, 100), 2)
    c = PRIMEIRO[uf] + random.uniform(-3, 3)
    w = 0.3 + 4 * (1 - pct / 100)
    ufs.append({
        "uf": uf,
        "nome": nome,
        "pct_secoes": pct,
        "apurado": round(c + random.uniform(-2, 2), 2),
        "projecao": {"centro": round(c, 2), "baixo": round(c - w, 2), "alto": round(c + w, 2)},
        "primeiro_turno": float(PRIMEIRO[uf]),
        "segundo_turno_anterior": round(PRIMEIRO[uf] + random.uniform(-4, 4), 2),
    })

doc = {
    "versao": 1,
    "exemplo": True,
    "eleicao": {"ano": 2026, "turno": 2, "cargo": "Presidente"},
    "candidatos": {
        "esq": {"nome": "Lula", "numero": 13, "partido": "PT"},
        "dir": {"nome": "Flávio Bolsonaro", "numero": 22, "partido": "PL"},
    },
    "fase": "apurando",
    "atualizado": serie[-1]["hora"],
    "nivel_faixa": 95,
    "projecao_desde_pct": 1.0,
    "serie": serie,
    "ufs": ufs,
    "validacao": {
        "eleicao": "2º turno de 2022",
        "erro_medio_pp": 0.2,
        "desde_pct": 5.0,
        "cobertura_faixa": 0.95,
    },
}
with open("site/dados/exemplo.json", "w", encoding="utf-8") as f:
    json.dump(doc, f, ensure_ascii=False, indent=1)
print(len(serie), "pontos")
