# Sprint 024 — Profiler causal e ablações

**Versão:** `0.25.0a1`

## Pergunta

Qual parte estrutural do grafo deve ser atacada antes de alterar o backend?

O profiler não usa wall time. Ele evita concluir causalidade a partir de uma
mediana instável e produz uma descrição refutável do trabalho compilado.

## Contabilidade por instrução

Cada instrução forward e backward registra:

- operador, estágio, shape e dtype;
- bytes lógicos de entrada e saída;
- materialização ou view;
- buffer físico, offset e live range;
- FLOPs escalares quando conhecidos;
- intensidade aritmética lógica;
- região de fusão;
- identidade, provedor e contrato do GEMM.

Transcendentais como `sigmoid` e `tanh` não recebem custo inventado. O relatório
marca seus FLOPs como desconhecidos.

## Resumo causal

O resumo calcula:

- fração dos FLOPs conhecidos em GEMM;
- tráfego lógico total;
- bytes de views não materializadas;
- reuso da arena;
- lançamentos de loop evitados por fusão;
- hipóteses priorizadas e o experimento que poderia refutá-las.

Bytes lógicos não são apresentados como tráfego DRAM. Cache, prefetch e
contadores de hardware continuam desconhecidos.

## Matriz de ablação

O artefato declara seis variantes:

- provedor próprio com 1, 2 e 4 workers;
- OpenBLAS com 4 workers e 1, 2 ou 4 threads GEMM.

As variantes são planos, não vencedores. Uma ablação temporal posterior precisa
manter grafo, entradas, afinidade e duração, preservar todas as falhas e passar
qualidade antes de velocidade.

## Comando

```console
t tensor-causal-profile \
  examples/tensor/mlp-mse-medium.tensor.json \
  --output build/causal-profile \
  --wrt weight1 weight2 \
  --workers 4 \
  --gemm-workers 1 \
  --provider openblas
```

O diretório contém `causal-profile.json` e `causal-profile.html`. O perfil é
imutável e selado por SHA-256, mas não é um pré-registro temporal.
