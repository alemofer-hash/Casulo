# Sprint 008 — buffer tipado e evidência lateral

## Hipótese

O custo dominante já não era a conta hidrológica, mas o trânsito intermediário
por dicionários, validações, evidências inline e clones de envelopes.

## Entrega

- `casulo-typed-buffer/0.1`;
- colunas contíguas `float64` e `int64`;
- índices de registros em `array('I')`;
- hits, estado e condições em `bytearray`;
- valores de evidência separados do envelope;
- manifestação somente na fronteira;
- fallback integral para o kernel de objetos;
- estratégia `FUSE_TYPED_BATCH`;
- sonda Borboleta de alocações;
- artefato 0.5, backend 0.4.1 e Casulo 0.8.

## Invariantes

1. conservar entrada, resultado, ordem, estado e evidência;
2. preservar a diferença entre inteiro e float;
3. preservar `+0.0` e `-0.0` na identidade;
4. nunca emitir estado parcial do caminho tipado;
5. retornar ao kernel de objetos diante de forma incompatível;
6. não incluir a sonda de memória nas amostras de velocidade;
7. não chamar tempo de CPU de energia elétrica.

## Resultado

Em 50% de repetição, com 21 amostras de dez iterações:

- kernel: `3,790×`, IC95% `3,446–4,250`;
- adaptativo ponta a ponta: `3,557×`, IC95% `3,388–3,752`;
- pico rastreado: redução de `31,00%`;
- equivalência semântica: preservada.

Com 0% de repetição, `FUSE_TYPED_BATCH` ainda atingiu `3,074×` no kernel e
`2,652×` ponta a ponta. Portanto, o resultado não depende somente de cache.

Os dados, amostras e relatórios estão no
[resumo da matriz](../../benchmarks/results/2026-07-29-sprint008-typed-buffer/SUMMARY.md).

## Gate

O Marco 2 exigia `2×` em tráfego intermediário, break-even abaixo de 50%,
conteúdo idêntico e redução mensurável de estruturas/bytes lógicos. Todos os
gates foram satisfeitos para o kernel e ambiente declarados. Contadores físicos
de tráfego de memória continuam fora do escopo deste laptop.

Isso não demonstra ganho universal, SIMD, paralelismo ou redução de joules.
