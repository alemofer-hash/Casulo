# Auditoria T para Semantic Multiverse

| ID | Evidência real | Estado |
|---|---|---|
| TSM-001 | strings/hash já validados em TCAP e domain | adaptado em `semantic_ir.py` |
| TSM-002 | manifests JSON canônicos existentes | adaptado, schema separado |
| TSM-003 | `TransitionDecl` histórico não cobre universos | Semantic IR explícita |
| TSM-004 | invariantes eram strings contratuais | preservação comum verificada |
| TSM-005 | `ResourceContract` mistura números/unidades | wrappers dimensionais adicionados |
| TSM-006 | runtime hosted já cancela jobs | lifecycle adaptado, sem sintaxe async nova |
| TSM-007 | effect checker T/1.1 existe | effects semânticos registrados |
| TSM-008 | receipts existem em Forge/simulation | receipt obrigatório na transição |
| TSM-009 | IR geral não representa universos | extensão `SemanticIRProgram`, não substituição |
| TSM-010 | Forge já calcula downstream closure | impact graph semântico explícito |
| TSM-011 | artifacts/TCAP possuem content hashes | store base+delta adaptado |
| TSM-012 | QPU não existe | RFC only, deny |

Não foi adicionada sintaxe T. O contrato semântico, tipos, diagnostics, lowering,
IR, effects, TCAP e goldens precedem qualquer RFC futuro de superfície. A rota
legada `parse_training_spec -> _render_training_c` continua inelegível para o
produto.
