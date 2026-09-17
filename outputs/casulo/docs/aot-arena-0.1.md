# AOT e arena nativa Casulo 0.1

## Contrato

O Sprint 010 adiciona três protocolos internos sem alterar
`casulo-native-abi/0.1`:

- `casulo-aot/0.1`: otimizações conservativas sobre a CrisálidaIR;
- `casulo-native-arena/0.1`: buffers reutilizáveis da fronteira nativa;
- `casulo-boundary-aot/0.1`: marshal e manifestação especializados por
  esquema.

O backend que os materializa é `c99-aot/0.2`.

## Otimizações AOT

Antes de gerar C99, cada operação elegível passa por:

1. análise reversa de vivacidade;
2. remoção de `let` cujo resultado não alcança evidência ou `emit`;
3. propagação de constantes numéricas finitas e representáveis em `float64`;
4. propagação de aliases sem efeitos;
5. geração C99 retilínea para o restante.

O descritor ABI registra contadores por operação:

```json
{
  "protocol": "casulo-aot/0.1",
  "instructions_before": 7,
  "instructions_after": 6,
  "dead_lets_removed": 1,
  "constants_propagated": 1,
  "aliases_propagated": 1
}
```

Somente expressões já aceitas pelo subconjunto C99 seguro são transformadas.

## Arena

`PreparedNativeExecutor` mantém:

- entrada colunar;
- resultados;
- estados;
- julgamentos e restrições;
- valores estabilizados;
- posição da primeira falha.

A capacidade cresce para a próxima potência de dois e não encolhe entre
chamadas. Isso retira alocação repetida das amostras e mantém o endereço dos
buffers estável enquanto couberem na arena.

Uma arena pertence a uma operação e biblioteca verificadas. Ela nunca é
compartilhada entre artefatos.

## Fronteira especializada

O esquema conhecido permite gerar duas funções Python pequenas:

- validação e cópia para as colunas em uma única travessia;
- manifestação direta do envelope, sem dicionários intermediários de estado.

`judge` e `restrict` ainda são executados no C99. Evidências são marcadas como
aprovadas somente depois que o kernel retorna status zero. Uma falha interrompe
a manifestação.

## Medição

`casulo-native-benchmark/0.2` publica:

- Python escalar com envelope completo;
- C99 ponta a ponta;
- marshal isolado;
- kernel C99 com entrada pré-materializada;
- manifestação isolada;
- amostras pareadas e IC95% bootstrap da mediana do ganho.

A soma dos estágios isolados é diagnóstica; o veredito usa a medição
ponta a ponta.

## Limites

- a ABI 0.1 continua restrita a lotes homogêneos `float64`;
- a arena é de um núcleo e não é thread-safe;
- manifestação Python ainda domina o tempo fora do kernel;
- não há SIMD explícito;
- não há medição de joules;
- o teste Linux é executado pela matriz de CI, não pelo laptop Windows.
