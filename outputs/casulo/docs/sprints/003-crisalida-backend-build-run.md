# Sprint 003 — Crisálida: backend, artefato, build e run

**Estado:** concluída localmente
**Versão:** `0.3.0a3`
**Data:** 29 de julho de 2026

## Objetivo

Transformar a CrisálidaIR tipada em um artefato executável, reproduzível,
íntegro e independente da IDE.

## Entregue

- backend Python de referência;
- gerador determinístico sem `ast.unparse`;
- runtime autocontido;
- CLI autocontida no módulo gerado;
- validação dos tipos de entrada;
- preservação integral da entrada no envelope;
- evidências de `judge`, `restrict`, `project`, `bind` e `stabilize`;
- semântica de `emit` e `if/else`;
- artefato `casulo-artifact/0.1`;
- fonte T preservada no artefato;
- CrisálidaIR JSON canônica;
- manifesto sem timestamp ou caminho absoluto;
- hashes SHA-256 de fonte, IR e executável;
- cache por identidade de conteúdo;
- recusa de sobrescrita de diretório divergente;
- verificação de integridade antes da execução;
- reconstrução fonte → IR → executável antes do carregamento;
- bloqueio de caminhos externos no manifesto;
- `t build`;
- `t run`;
- build implícito ao executar uma fonte `.t`.

## Pipeline alcançado

```text
fonte T
→ EggLexer
→ EggParser
→ LarvaAnalyzer
→ CrisálidaIR
→ PythonBackend
→ casulo-artifact/0.1
→ executor verificado
→ envelope conservativo
```

## Gate da sprint

```text
build idêntico em diretórios diferentes
segunda compilação é cache hit e não reescreve arquivos
artefato executa sem depender do checkout
casulo_artifact.py executa sem o pacote Casulo
entrada hidrológica é preservada integralmente
WaterBalance emite 65 para o caso canônico
judge falso bloqueia a emissão
schema incompleto bloqueia a execução
arquivo adulterado é rejeitado antes de executar
alteração coordenada de arquivo e hash também é rejeitada
diretório divergente nunca é sobrescrito
```

## Caso canônico

Entrada:

```json
{
  "precipitation": 100,
  "evapotranspiration": 10,
  "surface_flow": 20,
  "base_flow": 5
}
```

Resultado:

```text
storage_change = 100 - 10 - 20 - 5 = 65
state = stable
```

## Evidência de validação

| Ambiente | Resultado |
|---|---|
| Python 3.11 | 42 testes aprovados; 1 integração opcional ignorada |
| Python 3.12 | 42 testes aprovados; 1 integração opcional ignorada |
| Python 3.13 | 43 testes aprovados |
| instalação não editável | `t doctor`, `t build` e `t run` aprovados |

Os quatro arquivos do artefato canônico tiveram hashes idênticos nos três
interpretadores. O identificador comum foi:

```text
sha256:9f5612019d1641203abdea6b8a9bd5b46a3a929848f0f1cbb57fe7366d9f1185
```

## Limites conscientes

- execução unitária, sem lote;
- Python escalar;
- sem vetorização NumPy;
- sem grafo def-use;
- sem análise de custo;
- sem scheduler;
- sem paralelismo;
- sem backend nativo;
- sem kernels FLOOD-RS.

## Próxima sprint proposta

**Sprint 004 — Metamorfose: execução vetorial e grafo incremental**

Objetivo:

```text
CrisálidaIR
→ def-use
→ pureza e efeitos
→ execução em lote
→ cache por operação
→ benchmark contra Python ingênuo
→ primeira medição de energia e velocidade
```
