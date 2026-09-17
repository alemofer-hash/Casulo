# Título, pergunta e escopo vinculantes

## Título

**Princípio da Interlocução: a Linguagem T como arquiteta, auditora e juíza da
integridade semântica em modelos de treinamento de redes neurais artificiais e
a decorrente compressão física da informação preservada**

`Princípio` foi escolhido como análogo de engenharia porque designa uma regra
arquitetural condicionada, útil para projeto e falsificável por implementação,
sem sugerir demonstração universal da matemática pura.

## Pergunta principal

Uma linguagem de autoridade pode governar causalmente as decisões críticas de
treinamento, auditar o trabalho realmente executado e julgar sua integridade
semântica, reduzindo trabalho e estado líquidos quando preserva os observáveis
confirmados pelo usuário?

## Hipótese delimitada

Sob contrato semântico suficiente `R`, autoridade T causal, primitives
manifestadas, receipts internos e verificador independente, a execução aceita
pode preservar equivalência operacional relativa a `R`. Há compressão líquida
somente nas dimensões em que o custo eliminado superar todo overhead de T.

## Objeto empírico atual

- FloodSurrogate: 1.024 registros, 8 entradas, 8 unidades ocultas, 1 saída,
  ReLU, MSE, SGD, float64, full batch e 400 épocas;
- holdout linear com MAE;
- holdout logístico com BCE e working set parcial;
- braços A/B/C/D e nove mutações causais;
- um host e protocolo preservados na campanha.

## Fora do escopo probatório atual

- universalidade para toda rede/dataset;
- CNN e atenção como resultados já observados;
- energia de pacote ou tomada;
- GPU, cluster ou datacenter;
- solidez completa do verificador;
- produto Casulo, interface, voz ou sistema operacional como contribuição
  central deste manuscrito.

Esses itens podem aparecer como agenda de replicação, nunca como resultado.
