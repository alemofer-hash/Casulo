# Forense do evento de throttling do worker completo

## Conclusão

O evento de `2026-08-08T14:19:54.187000+00:00` é classificado como
`GENUINE_INSTANTANEOUS_THERMAL_THROTTLE`.

Três campos instantâneos e independentes estavam ativos na mesma amostra:

- `Estrangulamento térmico do núcleo (avg) [Yes/No] = Sim`;
- `P-core 1 Estrangulamento térmico [Yes/No] = Sim`;
- `Regulagem térmica do pacote / anel [Yes/No] = Sim`.

Os mesmos três campos estavam `Não` na amostra imediatamente anterior e na
imediatamente posterior. O parser não consultou colunas `Maximum` e reconhece
explicitamente `Sim`, `Não`, `Yes`, `No`, `1`, `0`, `verdadeiro` e `falso`.

## Exclusões causais

Na amostra do evento, `Temperatura crítica`, `IA: PROCHOT`, `GT: PROCHOT`,
`RING: PROCHOT` e os indicadores de limite de potência estavam inativos. O
campo `IA: Max Turbo Limit` estava ativo antes, durante e depois, portanto não
explica a transição térmica. A temperatura média dos núcleos registrada foi
68 °C; o valor não torna o sinal falso, pois a decisão é do indicador térmico
instantâneo exposto pelo processador/HWiNFO, não de um limiar inventado pelo
runner.

## Evidência preservada

- Linha original: 18456 do CSV HWiNFO.
- Recorte: 239 linhas, de 30 s antes até 30 s depois.
- Amostragem mediana: 0,251 s; p95: 0,267 s.
- Classificação estruturada: `throttle_classification.json`.
- Linhas brutas: `throttle_event_excerpt.csv`.

O evento não foi apagado, reinterpretado como power-limit nem convertido em
um estado histórico acumulado.
