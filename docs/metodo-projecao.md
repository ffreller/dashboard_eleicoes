# Método de projeção do 2º turno

A projeção é feita seção a seção. O modelo corrige o voto do 1º turno de 2026 pela mudança de voto que já apareceu nos municípios apurados. Implementação em `src/eleicao/modelo/projecao.py`.

## 1. Referência de cada seção
A base é a fração da esquerda entre os dois candidatos no 1º turno de 2026, na mesma seção, em logit. Cada seção também carrega o voto do mesmo local no 2º turno de 2022 e o perfil do lugar.

## 2. Swing medido
Em cada município que já começou a apurar, o swing é a mudança de voto entre o apurado e o 1º turno das mesmas seções totalizadas. `_swing_uniforme` resolve por Newton o deslocamento uniforme em logit que, somado a cada seção apurada, reproduz a fração observada. Subtrair logits agregados erra quando as seções são heterogêneas, e o erro passaria para as seções que faltam.

## 3. Regressão do swing
Uma regressão ponderada com priori normal explica o swing pelo perfil do lugar:
- outros (voto nos demais candidatos)
- dif_2t_anterior
- inclinacao
- outros_x_inclinacao
- capital
- porte
- abstencao
- brancos_nulos

Há interceptos nacional, por região e por UF, encolhidos para o nacional. As variâncias de município, UF e região têm piso fixo (`Parametros`) e são reestimadas com a dispersão observada na própria apuração, em 3 iterações (`_ajustar`). Uma eleição em que os estados divergem muito gera faixas mais largas.

## 4. Seções que faltam
Cada seção não totalizada recebe:
1. a referência do 1º turno dela;
2. o swing previsto para o perfil dela;
3. o desvio próprio do município, encolhido conforme a parte já apurada dele.

O total de votos válidos é o do 1º turno vezes a razão 2º/1º turno medida no município. Essa razão é encolhida para a da UF (peso de 5000 votos) e depois para a nacional.

## 5. Faixa e chance de vitória
A faixa vem de 300 sorteios (`Parametros.sorteios`). Cada sorteio varia:
- os coeficientes da regressão, tirados da posteriori;
- os desvios de município;
- as razões de válidos, por município e por UF;
- um choque comum nacional (`sd_ordem_nacional` 0,015) e outro por UF (`sd_ordem_uf` 0,02) sobre tudo o que falta.

O choque cobre o risco de as seções que chegam por último mudarem de voto de um jeito que as primeiras não mostram. O intervalo é de 95%. A chance de vitória é a fração dos sorteios com mais de 50%. A semente deriva dos dados da apuração, então a mesma apuração dá sempre a mesma faixa.

## 6. Validação
Os ensaios (`eleicao ensaio`) replayam os 2º turnos de 2022 e 2018 na ordem real de chegada das seções. `eleicao tse-falso` serve esse replay nos mesmos arquivos do TSE. Os pisos de região e UF foram calibrados entre a dispersão medida em 2022 (0,016 e 0,019) e em 2018 (0,076 e 0,099).
