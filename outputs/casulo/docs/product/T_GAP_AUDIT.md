# Auditoria de lacunas da Linguagem T

Baseline: commit `df12e916c90d9bd2b966326275dc191573f38abd`, com mudanças
preexistentes preservadas. Estado auditado em 2026-08-11.

| ID | Evidência real | Estado/decisão |
|---|---|---|
| T-GAP-001 | `workspace.py:251-264` validava existência e ordenava `use`; cada arquivo era analisado isoladamente | CLOSED_SPRINT_3; interfaces exportadas possuem SHA-256, schema e ligação cross-module com colisão `T3103` |
| T-GAP-002 | IR histórica era lista linear sem SSA/phi | PARTIAL_CLOSED_SPRINT_3; T/1.1 possui CFG verificável com blocos/sucessores; SSA/phi continua fora do corte |
| T-GAP-003 | grafo derivava strings de efeitos sem grant/checker estático | CLOSED_SPRINT_3; checker fecha effects, TCAP transporta requirements e broker continua deny-by-default |
| T-GAP-004 | grafo carrega `estimated_cost` estrutural | CONFIRMED; adaptar somente para estimativas locais de UX |
| T-GAP-005 | artefato/cache opera por operação/artefato; não existe invalidation closure por `IntentDelta` | CLOSED_PRODUCT_RUNTIME_SPRINT_7; T Forge propaga impacto a jusante e preserva hashes fora do subgrafo |
| T-GAP-006 | `training.py:190` expõe `parse_training_spec` e `training.py:1460` `_render_training_c`; `workspace.py:340-345` escolhe rota por `kind=training` | CONFIRMED; classificado LEGACY, não elegível para produto |
| T-GAP-007 | tensor IR e operadores existem, com foco rank-2/matmul | CONFIRMED; adiar operadores conforme casos reais de voz/inferência |
| T-GAP-008 | backend CPU/native existe; nenhuma HAL accelerator portável | CONFIRMED; definir contrato HAL antes de backend |
| T-GAP-009 | `typesys.py`, `backend.py`, `graph.py` e `native.py` usavam `ast.parse` | CLOSED_SPRINT_3; parser/AST T próprios em todo o pipeline; `ast.literal_eval` é usado apenas para decodificar literal |
| T-GAP-010 | C99/OpenBLAS existem por caminhos especializados; FFI geral capability-safe não existe | CONFIRMED; RFC ABI/FFI após effect system |
| T-NEW-001 | frontend não possuía record/enum/union T | PARTIAL_CLOSED_SPRINT_3; record/enum/Result implementados; union geral continua futuro |
| T-NEW-002 | operações `condense/transition`, sem funções/interfaces gerais | REQUIRED; planejar com módulo/linker |
| T-NEW-003 | frontend não possui async/stream/cancelamento | REQUIRED; structured concurrency após effects |
| T-NEW-004 | erros do compilador existem; `Result`, timeout/retry T não | PARTIAL_CLOSED_SPRINT_3; Result tipado existe, construção/match/timeout/retry aguardam RFC |
| T-NEW-005 | capability de produto ausente | CLOSED_SPRINT_3 para checker/requirements/broker mínimo |
| T-NEW-006 | memória persistente T ausente | REQUIRED após Living Memory |
| T-NEW-007 | eventos/gatilhos T ausentes | REQUIRED |
| T-NEW-008 | agente como construct T ausente | REQUIRED |
| T-NEW-009 | aprovação humana tipada ausente | REQUIRED |
| T-NEW-010 | adapters de modelo não fazem parte da linguagem | REQUIRED como capabilities substituíveis |
| T-NEW-011 | patch incremental T/IR/grafo ausente | CLOSED_PRODUCT_RUNTIME_SPRINT_7; sem alegar nova sintaxe T |
| T-NEW-012 | contrato de colaboração T ausente | REQUIRED |
| T-NEW-013 | simulação determinística de produto ausente | CLOSED_PRODUCT_RUNTIME_SPRINT_9_14; doubles, receipts, pause/resume/replay e comparação |
| T-NEW-014 | materialização atual gera artefatos T/Python/C; targets de produto e SBOM completos ausentes | CLOSED_PRODUCT_RUNTIME_SPRINT_10_14; package, API local, manifest, SBOM, hashes e round-trip |
| T-NEW-015 | schemas/migrações de produto ausentes | REQUIRED desde Sprint 1 |

## Revolution Closure RC4

Sem criar sintaxe nova, nove contratos T/1.1 passaram a expressar e executar
as superfícies congeladas de intenção/requisitos, agente, tools, memória, jobs,
capabilities, interface, simulação e materialização. Cada build preserva hashes
de fonte, IR, grafo e artefato. Fronteiras Python/C++/Rust são explícitas e
falham fechadas. A alegação permanece limitada à governança dessas decisões;
pesos, drivers e kernels continuam externos.

## Ordem vinculante

Congelar goldens T 1.0 → RFC effects/capabilities → expression AST → linker de
módulos/ABI → IR CFG → records/enums/result → concorrência → memória/eventos →
agentes/aprovação → delta compilation → materialização. Nenhuma nova sintaxe é
autorizada sem semântica, AST, diagnósticos, lowering, IR/grafo, goldens e
migração.
