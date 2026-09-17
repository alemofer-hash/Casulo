# Pacto científico Casulo/T 1.0

## Finalidade

O Pacto Científico torna a fidelidade uma propriedade executável do Casulo/T.
O sistema não escolhe se deseja ser rigoroso em cada experimento: o rigor é um
invariante anterior ao resultado.

O juiz científico pode classificar evidência. Ele não pode alterar código,
dataset, parâmetros, baseline, amostras ou limiares.

## Classificações possíveis

| Veredito | Significado |
|---|---|
| `POSITIVE` | qualidade válida e IC95% inferior acima do limiar |
| `NULL` | qualidade válida, mas o intervalo cruza o limiar |
| `NEGATIVE` | qualidade válida e IC95% superior abaixo do limiar |
| `INCONCLUSIVE` | baseline ou evidência obrigatória ausente |
| `INVALID` | integridade, desenho ou equivalência violados |

`POSITIVE` não é o estado padrão. Os cinco resultados são produtos legítimos.

## Invariantes

1. hipótese, métricas, baselines e gates são selados antes da medição;
2. equivalência e qualidade precedem velocidade;
3. baseline obrigatório ausente torna o resultado inconclusivo;
4. amostras brutas e ordem pareada são preservadas;
5. mediana sem incerteza não libera alegação;
6. resultados negativos, nulos e falhas permanecem publicados;
7. grandeza não medida permanece `null`;
8. todas as execuções pré-registradas entram no veredito;
9. toda alegação é limitada à carga, baseline e máquina medidos;
10. correção lógica cria nova versão e não sobrescreve a anterior;
11. o juiz recalcula métricas a partir das amostras;
12. o juiz não possui funções de otimização.

## Fluxo

```text
EggPreRegistro
→ código, dataset, baselines, amostras e limiares selados

LarvaObservação
→ execução preserva amostras e falhas

CrisálidaCritérios
→ qualidade, integridade e incerteza

MetamorfoseAuditoria
→ métricas recalculadas sem consultar o resultado desejado

BorboletaVeredito
→ POSITIVE | NULL | NEGATIVE | INCONCLUSIVE | INVALID

QuarentenaCientífica
→ dado ausente, alterado, incomparável ou não medido
```

## Comandos

Pré-registrar:

```console
t scientific-preregister examples/t/flood_surrogate_training.t \
  --output evidence/preregistration.json \
  --baseline pytorch-eager-cpu \
  --baseline pytorch-compile-inductor-cpu
```

Executar exatamente o desenho:

```console
t training-experiment examples/t/flood_surrogate_training.t \
  --output benchmarks/results/scientific-run \
  --samples 21 \
  --warmups 3 \
  --baseline pytorch-compile-inductor-cpu \
  --preregistration evidence/preregistration.json
```

O baseline compilado mede o regime aquecido. O custo inicial do Inductor é
medido em `baseline.compilation_wall_ns` e nunca é ocultado dentro ou fora das
amostras sem indicação explícita. O pré-registro 1.1 também sela os hashes do
executor de treinamento e do juiz científico.

Julgar e verificar:

```console
t scientific-judge \
  --preregistration evidence/preregistration.json \
  --report benchmarks/results/scientific-run/training-report.json \
  --output evidence/verdict.json

t scientific-verify \
  --preregistration evidence/preregistration.json \
  --report benchmarks/results/scientific-run/training-report.json \
  --probe evidence/pytorch-compile-probe.json \
  --verdict evidence/verdict.json
```

## Correção de lógica

Uma otimização pode falhar porque é impossível para a carga ou porque a
implementação está inadequada. Investigar e corrigir a implementação é
permitido. O que não é permitido:

- mudar o limiar depois de ver o resultado;
- apagar a execução anterior;
- reutilizar o mesmo pré-registro após mudar o código;
- apresentar somente a melhor repetição;
- transformar indisponibilidade em ausência silenciosa.

Depois de uma correção:

```text
evidência anterior preservada
+ novo código/protocolo
+ novo pré-registro
+ nova execução completa
```

## Limitação temporal atual

O selo SHA-256 demonstra integridade, mas ainda não fornece sozinho um carimbo
de tempo externo confiável. A ordem é sustentada pelo arquivo e pelo histórico
Git. Um serviço de timestamp independente poderá ser acoplado futuramente.

## Marca

Casulo é um invento original da Teloscorp para Otimização de Tráfego de
Informação.
