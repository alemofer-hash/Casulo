# TCAP v2

Schema: `casulo.tcap/2.0`  
Implementação: `src/casulo/t/v2_tcap.py`

## Seções obrigatórias

`header`, `module_graph`, `typed_ir`, `functional_code`, `readonly_data`,
`effects`, `capabilities`, `resource_budgets`, `schemas`, `source_map`, `tests`,
`foreign_boundaries`, `provenance` e `signature_class`.

Cada seção é um arquivo JSON UTF-8 com SHA-256 no `MANIFEST.json`. Sources T
também são preservados e hashados. `tcap_hash` deriva de schema, mapa de seções
e sources. A assinatura de release é externa ao TCAP e continua
`DEVELOPMENT_NOT_COMMERCIAL`.

## Código funcional

`code.json` contém opcodes estruturados derivados da AST/IR: contracts,
branching, match, loop bounded, state, effects, events, Result e jobs. Um agente
de gate precisa conter comportamento funcional; `[RET]` vazio e
`emit_literal` não satisfazem a especificação.

## Verificação

O loader confina caminhos à raiz, verifica todos os hashes, sources e a
identidade TCAP antes de entregar IR. O verifier hosted recompila cada source T
e exige igualdade exata entre source, module graph, typed IR e bytecode. Rust e
Native validam estrutura/opcodes, identidade, effects/capabilities e budgets
antes de executar. A verificação de assinatura pertence ao release/Trust Plane.

## Compatibilidade

TCAP v2 não substitui nem reinterpreta `casulo-artifact/0.8`; ambos coexistem
durante a migração. Importação precisa declarar versão, e downgrade não é
silencioso.
