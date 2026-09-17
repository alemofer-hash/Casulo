# Sprint 002 — Larva: símbolos, tipos e CrisálidaIR

**Estado:** concluída localmente
**Versão:** `0.2.0a2`
**Data:** 29 de julho de 2026

## Objetivo

Transformar a AST da Sprint Egg em um programa semanticamente resolvido e
tipado, capaz de produzir uma representação intermediária estável.

## Entregue

- tabela de símbolos;
- escopo raiz, de field, de operação e de ramo;
- símbolos de módulo, importação, field, trace, operação e variável local;
- resolução de nomes;
- detecção de redefinição;
- tipos semânticos;
- inferência de literais, nomes, listas, operadores, comparações e chamadas;
- assinaturas das funções congeladas;
- validação booleana de `judge`, `restrict` e `if`;
- inferência do tipo de retorno;
- rejeição de emissões incompatíveis;
- prova estrutural de `emit` em todos os caminhos;
- CrisálidaIR textual e JSON;
- `t inspect --symbols`;
- `t inspect --ir`;
- golden textual da IR hidrológica;
- expansão do corpus para 42 programas T.

## Pipeline alcançado

```text
fonte T
→ EggLexer
→ EggParser
→ AST
→ LarvaAnalyzer
→ tabela de símbolos
→ tipos
→ gate de emissão
→ CrisálidaIR
```

## Diagnósticos adicionados

| Código | Gate |
|---|---|
| `T3030` | nome não resolvido |
| `T3031` | redefinição no escopo |
| `T3032` | condição não booleana |
| `T3033` | incompatibilidade de tipo |
| `T3034` | emissões incompatíveis |
| `T3035` | função desconhecida |
| `T3036` | aridade inválida |
| `T3039` | tipo de projeção desconhecido |

## Gate da sprint

```text
t check detecta nomes, tipos e emissão
t inspect --symbols produz tabela estável
t inspect --ir produz CrisálidaIR
programa inválido não produz IR
golden tests permanecem verdes
```

## Evidência de validação

| Ambiente | Resultado |
|---|---|
| Python 3.11 | 26 testes aprovados; 1 integração opcional ignorada |
| Python 3.12 | 26 testes aprovados; 1 integração opcional ignorada |
| Python 3.13 | 27 testes aprovados |
| instalação limpa, não editável | pacote `casulo-0.2.0a2` instalado; `t doctor`, `t check` e `t inspect --ir` aprovados |

O corpus de conformidade contém 42 programas T, entre casos válidos e
inválidos, com diagnósticos esperados declarados no manifesto.

## Programa FLOOD-RS canônico

Inferência obtida:

```text
HydroCell.precipitation: Number
HydroCell.evapotranspiration: Number
HydroCell.surface_flow: Number
HydroCell.base_flow: Number
WaterBalance.storage_change: Number
WaterBalance: HydroCell -> Number
```

## Limites conscientes

Ainda não existem:

- resolução de módulos `use`;
- acesso qualificado;
- tipos científicos de unidade, datum e array;
- IR em SSA;
- grafo def-use;
- backend Python;
- `t build`;
- `t run`;
- cache;
- runtime nativo.

## Próxima sprint proposta

**Sprint 003 — Crisálida: backend Python de referência**

Objetivo:

```text
CrisálidaIR
→ código Python determinístico
→ artefato com manifesto
→ t build
→ t run
→ cache por hash
```

Gate:

```text
build reproduzível
segunda execução não recompila
resultado do balanço hídrico validado
artefato independente da IDE
```
