# Sprint 004 — Metamorfose: grafo, lote, cache e benchmark

**Estado:** concluída localmente
**Versão:** `0.4.0a4`
**Data:** 29 de julho de 2026

## Objetivo

Transformar o artefato escalar da Crisálida em uma execução observável,
repetível e mensurável sobre lotes.

## Entregue

- `metamorfose-graph/0.1`;
- nós estáveis de entrada e instrução;
- arestas def-use;
- arestas de controle;
- efeitos `guard`, `evidence` e `manifest`;
- determinismo e capacidade de cache explícitos;
- estimativa estrutural de custo;
- `t inspect --graph`;
- grafo incorporado e verificado no artefato;
- `casulo-artifact/0.2`;
- `python-reference/0.2`;
- kernel de lote fundido;
- execução automática de listas JSON;
- `--batch`;
- `--no-cache`;
- cache SHA-256 separado por operação;
- deduplicação de entradas dentro do lote;
- preservação da ordem;
- `metamorfose-benchmark/0.1`;
- comparação escalar versus lote;
- digest de equivalência obrigatório;
- tempo de parede e tempo de CPU;
- correção lexical de `true`, `false` e `null` dentro de strings.

## Pipeline alcançado

```text
fonte T
→ CrisálidaIR
→ grafo da Metamorfose
→ kernel escalar
→ kernel de lote
→ cache operacional
→ benchmark equivalente
→ relatório auditável
```

## Gate

```text
grafo canônico coberto por golden
dependências de dados e controle verificadas
lote e escalar emitem o mesmo digest
duplicatas são calculadas uma vez
ordem da entrada é preservada
cache pode ser desativado
benchmark nunca chama proxy de joules
artefato continua standalone
```

## Baseline

O ensaio local com 3.000 registros por amostra, 10 iterações e 7 amostras
mediu:

```text
escalar: 19.475 registros/s
lote:    21.804 registros/s
ganho de parede: 1,1196x
razão de CPU:    1,1395x
```

O resultado é específico desta máquina, carga e operação.

## Evidência de validação

| Ambiente | Resultado |
|---|---|
| Python 3.11 | 53 testes aprovados; 1 integração opcional ignorada |
| Python 3.12 | 53 testes aprovados; 1 integração opcional ignorada |
| Python 3.13 | 54 testes aprovados |
| instalação não editável | `doctor`, grafo, build, lote e benchmark aprovados |

Fonte, CrisálidaIR, grafo, módulo Python e manifesto foram byte a byte
idênticos nos três interpretadores. O identificador comum foi:

```text
sha256:560ff4b760b1f4e48c4dfbcbfa7b6edba2d81fb1449ec7e6578a18026a91daf4
```

## Limites conscientes

- lote fundido ainda é Python escalar;
- sem NumPy, SIMD ou GPU;
- sem paralelismo;
- cache apenas em memória e por processo;
- sem invalidação por nó;
- custo do grafo não está calibrado;
- energia elétrica não foi medida.

## Próxima sprint proposta

**Sprint 005 — Borboleta: experimento científico e pacote público**

```text
datasets sintéticos versionados
→ harness estatístico
→ medição elétrica quando disponível
→ relatório HTML/JSON
→ API estável
→ release GitHub reproduzível
```
