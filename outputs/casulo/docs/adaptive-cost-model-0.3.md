# Modelo adaptativo Crisálida 0.3

## Objetivo

O protocolo `casulo-adaptive/0.3` impede que cache e deduplicação sejam tratados
como otimizações universais. A Larva mede a forma do lote, a Crisálida escolhe
uma estratégia e a Metamorfose manifesta a decisão junto à saída.

```text
entrada
→ PerfilLarva
→ ModeloCrisalida
→ DecisaoCrisalida
→ MetamorfoseAdaptativa
→ saída + justificativa
```

## PerfilLarva

O perfil contém:

- quantidade total e quantidade única;
- registros repetidos e taxa de repetição;
- bytes canônicos totais e médios;
- memória estimada do cache.

Em lotes de até 256 registros, a igualdade é exata. Em lotes maiores, a Larva
percorre 256 posições por uma permutação modular determinística, usa a chave
compilada e conta pares coincidentes. A concentração estima a multiplicidade
efetiva — a fração de execuções que o cache pode evitar.

O perfil amostral decide apenas se a otimização pode ser tentada. Quando a
deduplicação é escolhida, o backend continua verificando todas as entradas com
sua chave conservativa exata.

## Metadados do artefato

Cada operação do formato `casulo-artifact/0.8` manifesta:

```json
{
  "optimization": {
    "cacheable": true,
    "deterministic": true,
    "effects": ["guard", "evidence", "manifest"],
    "estimated_cost": 8,
    "key_protocol": "casulo-structural-key/0.1",
    "cache_scope": "batch-local",
    "buffer_protocol": "casulo-typed-buffer/0.1",
    "manifestation": "boundary"
  }
}
```

O custo vem do grafo da Metamorfose e não de uma anotação manual escondida.

## Estratégias 0.3

### RECALCULATE

Executa o kernel de lote sem cache. É escolhida quando:

- a operação não é cacheável;
- o lote possui menos de 64 registros no caminho de objetos ou menos de 8 no
  caminho tipado;
- a memória estimada excede o orçamento;
- a repetição não supera a fronteira com margem de segurança.

### FUSE_TYPED_BATCH

Extrai colunas `float64` ou `int64`, mantém índices e evidências em buffers
laterais e manifesta os objetos somente na fronteira. Pode ser escolhido mesmo
sem repetição, porque evita o kernel intermediário baseado em dicionários.

### DEDUPLICATE_BATCH

Forma chaves exatas, executa somente entradas únicas e manifesta cada resultado
na posição original. O cache começa vazio em cada execução adaptativa.

## Fronteira

A fronteira inicial foi calibrada pela primeira curva Borboleta:

```text
threshold =
  0,30
  - alívio_por_custo_da_operação
  + penalidade_por_tamanho_do_registro
```

Uma margem conservadora de `0,01` é adicionada antes de liberar deduplicação.
Para o `WaterBalance`, custo 8, isso conserva recomputação no regime de 25% e
permite deduplicação no regime de 40% observado pela Borboleta.

Operações mais caras recebem uma fronteira menor, porque evitar uma execução
cara paga o custo da chave mais rapidamente.

O modelo é explicitamente uma heurística `casulo-cost-model/0.3`. Ele não deve
ser apresentado como modelo universal ou aprendido.

## Uso

```console
t run artefato --input lote.json --adaptive
t run artefato --input lote.json --adaptive --memory-budget-mb 256
```

```python
from casulo.t import run_adaptive_artifact

execution = run_adaptive_artifact(
    "artefato",
    payloads,
    memory_budget_bytes=256 * 1024 * 1024,
)
print(execution.decision.strategy)
```

## Envelope

A saída normal do lote recebe:

```json
{
  "adaptation": {
    "profile": {},
    "decision": {
      "strategy": "RECALCULATE",
      "reasons": [],
      "estimated_speedup": 0.5,
      "confidence": 1.0
    }
  }
}
```

A decisão nunca remove entrada, resultado, evidência ou telemetria existente.

## Limitações

- o perfil amostral pode errar a cardinalidade em distribuições adversariais;
- entradas com tipos numéricos mistos usam o caminho de objetos;
- a calibração inicial veio de uma máquina e um kernel;
- o modelo ainda não aprende com execuções anteriores;
- `estimated_speedup` é direcional, não uma previsão de nanossegundos;
- SIMD e paralelismo ainda não são estratégias selecionáveis.

## Medição

O protocolo Borboleta 0.4 mede uma terceira trajetória:

```text
PerfilLarva + ModeloCrisalida + estratégia escolhida
```

Portanto, o fator adaptativo publicado inclui o custo da própria escolha. O
relatório também separa o custo de seleção, o arrependimento contra o melhor
caminho mediano e a correção da previsão quando o intervalo estatístico permite
identificar um vencedor.

## Próxima versão

O protocolo deverá calibrar por classe de operação, persistir previsão versus
observação e detectar mudança de regime.
