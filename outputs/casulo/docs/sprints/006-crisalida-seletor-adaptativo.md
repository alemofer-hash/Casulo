# Sprint 006 — seletor adaptativo Crisálida

## Problema

A Borboleta demonstrou que deduplicação pode piorar kernels baratos. O runtime
anterior sempre dependia de uma decisão manual sobre cache.

## Entrega

- formato de artefato 0.3 com metadados de otimização;
- `PerfilLarva`;
- `ModeloCrisalida`;
- `DecisaoCrisalida`;
- `MetamorfoseAdaptativa`;
- estratégias `RECALCULATE` e `DEDUPLICATE_BATCH`;
- orçamento de memória;
- comando `t run --adaptive`;
- decisão e razões incorporadas ao envelope;
- previsão comparada ao melhor caminho observado pela Borboleta;
- matriz unitária de repetição, custo e memória.

## Lei operacional

Na dúvida, recalcular. Deduplicação somente é liberada quando a repetição supera
a fronteira calculada e a memória cabe no orçamento.

## Critério de saída

1. escolher recomputação no regime de 90% do kernel canônico;
2. escolher deduplicação no regime de 95%;
3. bloquear cache quando o orçamento for insuficiente;
4. reduzir a fronteira para operações caras;
5. preservar integralmente entrada, ordem, saída e evidências;
6. explicar a decisão em JSON;
7. não regredir os três Pythons suportados.

## Evidência de fechamento

O laboratório executou nove amostras de cinco iterações, com dois aquecimentos,
2.000 registros e 2.000 reamostragens bootstrap em cada ponto. O tempo
adaptativo inclui perfil, decisão e execução.

| Repetição declarada | Repetição estimada | Decisão | Fator adaptativo | IC95% | Veredito |
|---:|---:|---|---:|---:|---|
| 0% | 0,00% | `RECALCULATE` | 1,091× | 0,901–1,278 | inconclusivo |
| 25% | 20,85% | `RECALCULATE` | 0,941× | 0,864–1,040 | inconclusivo |
| 50% | 51,30% | `RECALCULATE` | 1,077× | 0,986–1,119 | inconclusivo |
| 75% | 70,90% | `RECALCULATE` | 1,014× | 0,866–1,160 | inconclusivo |
| 90% | 91,25% | `RECALCULATE` | 1,084× | 1,031–1,176 | melhoria |
| 95% | 95,20% | `DEDUPLICATE_BATCH` | 0,927× | 0,886–1,076 | inconclusivo |
| 99% | 99,00% | `DEDUPLICATE_BATCH` | 1,106× | 1,023–1,242 | melhoria |

Não houve regressão adaptativa estatisticamente conclusiva. Nos regimes de 0%
a 75%, a deduplicação forçada perdeu de forma conclusiva e o seletor evitou
essa escolha. A fronteira de 95% permanece ruidosa e, por isso, não autoriza
uma alegação de ganho.

Relatórios, datasets e amostras brutas estão em
`benchmarks/results/2026-07-29-sprint006-adaptive`.

## Próximo gargalo

O seletor evita a escolha errada, mas o backend deduplicado ainda forma sua
chave conservativa com JSON + SHA-256 para todas as entradas. O Sprint 007 deve
substituí-la por chave estrutural tipada e cache local especializado.
