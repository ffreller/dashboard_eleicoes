# Ensaio com o 1º turno de 2026

Este ensaio mostra o que o modelo de projeção diria na noite do 1º turno de 2026 (4/10) se fosse usado para Lula × Flávio Bolsonaro. As seções entram na ordem real em que o TSE as totalizou.

## Resultado

Com 50% das seções apuradas (18h46), o modelo projetaria Lula com **48,89%** entre os dois. A faixa de 95% iria de 48,54% a 49,28%. O resultado final foi **48,99%**, então o erro foi de −0,10 ponto e o final ficou dentro da faixa.

A contagem naquele momento dava Lula com 45,40%. O modelo fechou quase toda a diferença de 3,6 pontos entre a contagem parcial e o resultado final.

A partir de 1,5% apurado, o erro não passou de 0,22 ponto. O resultado final ficou dentro da faixa nos 21 pontos medidos. Esses pontos vêm da mesma noite e não são independentes, então o resultado mostra uma noite boa e não prova que a faixa está calibrada.

## Todos os pontos

Valores em % de Lula entre os dois candidatos. O erro é a projeção menos o resultado final (48,99%), em pontos percentuais. A chance é a fração dos sorteios em que Lula termina acima de 50% entre os dois.

| Seções apuradas | Hora | Contagem | Projeção | Faixa | Chance | Erro |
|---:|---:|---:|---:|---:|---:|---:|
| 0,1% | 17:19 | 32,97 | 50,26 | 46,75 a 53,68 | 56,0% | +1,27 |
| 0,25% | 17:20 | 39,66 | 50,27 | 48,35 a 52,29 | 62,0% | +1,28 |
| 0,5% | 17:20 | 46,52 | 49,16 | 46,98 a 51,24 | 23,0% | +0,18 |
| 1% | 17:20 | 46,35 | 48,37 | 46,59 a 50,24 | 4,0% | −0,62 |
| 1,5% | 17:23 | 46,25 | 48,95 | 47,58 a 50,33 | 6,7% | −0,04 |
| 2% | 17:28 | 46,02 | 49,16 | 48,13 a 50,33 | 10,3% | +0,18 |
| 3% | 17:33 | 45,54 | 49,14 | 48,17 a 50,24 | 6,0% | +0,15 |
| 4% | 17:36 | 45,23 | 49,04 | 48,05 a 49,99 | 2,3% | +0,05 |
| 5% | 17:40 | 45,03 | 48,89 | 48,00 a 49,74 | 0,3% | −0,10 |
| 7% | 17:45 | 44,69 | 48,90 | 48,17 a 49,64 | 0,3% | −0,09 |
| 10% | 17:53 | 44,46 | 48,86 | 48,25 a 49,51 | 0,0% | −0,13 |
| 12,5% | 17:58 | 44,32 | 48,77 | 48,08 a 49,36 | 0,0% | −0,22 |
| 15% | 18:09 | 44,29 | 48,81 | 48,23 a 49,61 | 0,3% | −0,18 |
| 17,5% | 18:11 | 44,29 | 48,79 | 48,21 a 49,40 | 0,0% | −0,19 |
| 20% | 18:14 | 44,37 | 48,79 | 48,21 a 49,40 | 0,0% | −0,20 |
| 25% | 18:20 | 44,56 | 48,80 | 48,29 a 49,29 | 0,0% | −0,18 |
| 30% | 18:25 | 44,74 | 48,80 | 48,32 a 49,31 | 0,0% | −0,19 |
| 35% | 18:31 | 44,83 | 48,83 | 48,36 a 49,28 | 0,0% | −0,16 |
| 40% | 18:36 | 45,04 | 48,85 | 48,37 a 49,34 | 0,0% | −0,14 |
| 45% | 18:41 | 45,22 | 48,87 | 48,45 a 49,29 | 0,0% | −0,12 |
| 50% | 18:46 | 45,40 | 48,89 | 48,54 a 49,28 | 0,0% | −0,10 |

## Como o ensaio foi montado

No 2º turno, o modelo usa como referência o 1º turno do mesmo ano, nas mesmas seções. Aqui isso seria circular, porque o 1º turno de 2026 é o que se quer projetar. Por isso as duas referências voltam para 2022:

- **Base A.** O 1º turno de 2022 na mesma seção (Lula 13 × Bolsonaro 22). 92,4% das seções de 2026 acharam a mesma seção em 2022. As demais recebem as taxas por eleitor apto do seu município em 2022, ou da UF quando o município não tem dados.
- **Base B.** O 2º turno de 2022, pareado por local de votação com a mesma escada de `src/eleicao/base/pareamento.py`.
- **Alvo.** Os votos de Lula (13) e Flávio (22) em cada seção do 1º turno de 2026, com a hora em que cada seção foi totalizada.

Nenhum voto de 2026 entra nas referências. A única informação de 2026 que o modelo recebe antes da contagem é o número de eleitores aptos de cada seção, que se conhece antes da eleição. O modelo e os parâmetros são os mesmos do acompanhamento ao vivo.

Este teste é mais difícil que o 2º turno. A referência tem quatro anos, e o candidato da direita mudou de Jair para Flávio Bolsonaro.

## Limitações

- O ensaio considera só Lula e Flávio. Os 48,99% são a fatia de Lula entre os dois, e não o percentual dele nos votos válidos do 1º turno.
- A chance mede se Lula termina acima de 50% entre os dois. Ela diz quem termina à frente, e não quem venceria o 1º turno.
- O ensaio vai até 50% das seções, que é o ponto que motivou a pergunta.

## Reproduzir

Da raiz do repositório. O script lê os dados abertos do TSE de 2022 e 2026 em `data/raw/` e baixa o que faltar:

```sh
uv run python scripts/ensaio_1t2026.py
```

O script leva cerca de 1min40. Ele imprime a tabela acima e grava `site/dados/exemplo-1t2026.json`, que a página mostra em `?exemplo=1t2026`.
