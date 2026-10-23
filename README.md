# Apuração do 2º turno de 2026 com projeção

Página que acompanha a apuração do 2º turno presidencial de 2026 (Lula × Flávio Bolsonaro) e projeta o
resultado final a partir das seções já totalizadas pelo TSE.

O pipeline em Python lê a divulgação do TSE a cada ciclo e grava `site/dados/projecao.json`. A página em
`site/` lê esse arquivo e não tem etapa de build.

## Como a projeção funciona

Cada seção tem duas referências: o voto dela no 1º turno de 2026 e o voto do mesmo local no 2º turno de
2022. Em cada município que já começou a apurar, o modelo mede a mudança de voto entre o apurado e o 1º
turno das mesmas seções. Uma regressão explica essa mudança pelo perfil do lugar e a aplica às seções que
faltam. A faixa vem de 200 sorteios e inclui um choque comum para tudo o que falta.

O detalhe está em `src/eleicao/modelo/projecao.py` e na seção "Detalhes técnicos" da página.

## Preparar (uma vez)

```sh
uv sync
uv run eleicao base --ano 2026   # baixa ~350 MB do TSE e monta data/base/2026/
uv run pytest
```

Para refazer os ensaios (2º turnos de 2022 e 2018, na ordem real de chegada):

```sh
uv run eleicao base --ano 2022 && uv run eleicao ensaio --ano 2022
uv run eleicao base --ano 2018 && uv run eleicao ensaio --ano 2018
```

O resultado fica em `data/ensaio/<ano>.json`.

## No domingo

Em um terminal, rode o acompanhamento. Antes das 17h ele grava a fase `aguardando`:

```sh
uv run eleicao ao-vivo --intervalo 30
```

Em outro terminal, sirva a página:

```sh
uv run eleicao servir --porta 8000
```

Para publicar, sirva a pasta `site/` em qualquer hospedagem estática e envie `site/dados/projecao.json` a
cada ciclo. Se o processo cair, rode o mesmo comando de novo: a série já gravada é preservada.

## Ensaiar o domingo

O TSE falso serve um cenário conhecido nos mesmos arquivos da divulgação, com o relógio acelerado:

```sh
uv run eleicao tse-falso --ano 2022 --velocidade 30
uv run eleicao ao-vivo --ano 2022 --url-base http://localhost:8765/oficial --intervalo 5
uv run eleicao servir
```

Para ver a página com dados fictícios, abra `http://localhost:8000/?exemplo` (a apuração de 2026 simulada
até a metade, com o modelo de verdade) ou `?exemplo=aguardando|inicio|vantagem|encerrada`. Para refazer
a simulação da metade: `uv run python scripts/gerar_exemplo_metade.py`.

## Fontes

- Divulgação de resultados do TSE: `resultados.tse.jus.br` (eleição 6258, pleito 3221).
- Dados abertos do TSE: votação e detalhe da apuração por seção eleitoral (2014, 2018, 2022 e 2026).
