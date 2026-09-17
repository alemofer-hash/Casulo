# Equivalencia semantica operacional

## Contrato

Um requirement possui `id`, `kind` (`HARD` ou `SOFT`), predicado observavel,
fonte, tolerancia, verificador e estado. Estados permitidos: `PASS`, `FAIL`,
`UNKNOWN` e `BLOCKED`. Ausencia de evidencia nunca significa `PASS`.

Para o FloodSurrogate de contagem fixa, `R_flood_v1` exige:

- dataset content-addressed com 1.024 registros e oito entradas;
- topologia 8-8-1, ReLU, MSE, SGD, full batch, float64;
- inicializacao content-addressed;
- 400 epocas, forwards, backwards e optimizer steps;
- 409.600 visitas a registros e 32.400 escritas de parametros;
- ausencia de NaN/Infinity;
- perda, 81 parametros e 1.024 predicoes dentro de `1e-9`;
- estado do otimizador e motivo de parada coerentes com a politica;
- receipts internos completos, unicos, ordenados e encadeados.

`T_R(P) equiv_R P` somente se cada requisito HARD for `PASS` em um verificador
que le evidencias de ambos os processos. Contagens fixas sao parte deste
contrato e nao podem ser removidas em nome de early stopping.

## Contrato com parada semantica

Um experimento de early stopping precisa de outro `R`, congelado antes da
execucao. Nele, qualidade, estabilidade e tolerancia de parada substituem a
igualdade de contagem. O resultado deve reportar trabalho diferente e nao pode
ser comparado como se fossem 400 epocas equivalentes.

## Falso PASS

Qualquer um dos seguintes invalida a instancia:

- receipt produzido somente pelo runner;
- contador inferido a partir de `K` solicitado;
- resultado numerico plausivel sem trabalho integral;
- tolerancia alterada depois do resultado;
- verificador que importa o trainer ou confia em `analysis.json`;
- juiz T nao consumido pelo publicador;
- `UNKNOWN` ou receipt ausente convertido em aceitacao.

## Independencia minima

O verificador final roda em processo separado, recalcula hashes e cadeia,
recompoe contadores e custos a partir de dados brutos, e nao importa o modulo do
trainer. Ele pode compartilhar schemas versionados, mas nao funcoes de decisao.

