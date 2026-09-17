# Sprint 025 — Agenda GEMM adaptativa

**Versão:** `0.25.0a1`
**Estado:** implementação candidata validada; ablação temporal pendente

## Hipótese

Usar o mesmo número de threads em todas as multiplicações matriciais desperdiça
coordenação nas GEMMs pequenas. Uma agenda por shape pode manter dois workers
nas GEMMs suficientemente grandes e executar as menores com um worker.

Essa hipótese é estrutural. Ela não contém uma promessa de speedup.

## Política 0.1

A opção `--gemm-workers adaptive` sela
`shape-adaptive-flop-thresholds/0.1`. Para cada GEMM:

- quatro workers exigem ao menos 8.000.000 FLOPs escalares conhecidos e duas
  dimensões úteis com tamanho mínimo 32;
- dois workers exigem ao menos 2.000.000 FLOPs e duas dimensões úteis com
  tamanho mínimo 16;
- qualquer outro caso recebe um worker.

O teto continua sendo o orçamento global. Sob o Thermal Covenant, os blocos
experimentais usam no máximo dois workers. O plano registra
`gemm_worker_policy` e `gemm_worker_schedule`; a fonte C99 incorpora a decisão
em cada GEMM, inclusive ao configurar o provedor externo.

## Ordem de validação

1. plano determinístico e codegen estático;
2. compilação e paridade candidato versus NumPy;
3. ablação Casulo fixa versus adaptativa, em blocos de 250 ms;
4. somente depois, reabertura de PyTorch eager e Inductor.

Cada bloco depende de temperatura inicial de até 55 °C, watchdog externo,
máximo de 20 segundos e paralelismo limitado a dois workers. Qualquer warning,
throttling ou manifestação física anormal invalida a sessão.

## Limites científicos

Os thresholds são uma hipótese de engenharia prévia ao benchmark. Se a agenda
perder ou oscilar, o resultado negativo permanece registrado. A calibração de
250 ms demonstrou estabilidade apenas para o MLP médio candidato no host
registrado; não prova generalização, ganho energético nem superioridade.

## Primeiro fechamento térmico

Em 31 de julho de 2026, dois caminhos candidatos foram executados no grafo
`heldout-wide`, sempre com dois workers máximos, sete amostras e janela de
250 ms:

| Provedor | Agenda | Paridade | CV | Pico | Watchdog |
|---|---|---|---:|---:|---|
| próprio | `(2, 1, 1, 1, 2)` | `PASS` | 10,95% | 53 °C | passou |
| OpenBLAS | `(2, 1, 1, 1, 2)` | `PASS` | 7,68% | 54 °C | passou |

Nenhuma sessão registrou warning ou throttling. As medianas permanecem dados
diagnósticos: os dois caminhos não formaram uma comparação pareada
pré-registrada, portanto não sustentam speedup entre provedores.

O operador também atestou ausência de odor, fumaça e ruído anormal. O gate do
ciclo aceitou três de três sessões e autorizou a continuidade controlada.

O próximo bloco científico é uma ablação pré-registrada entre agenda fixa e
adaptativa. PyTorch e Inductor continuam fora do processo até esse gate ser
concluído.
