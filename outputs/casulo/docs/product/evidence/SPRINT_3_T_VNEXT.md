# Evidência — Sprint 3 T vNext Foundations

Data: 2026-08-11

## Gate

```text
160 passed, 42 subtests passed in 7.03s
public files scanned: 12
public forbidden findings: 0
cloud release state: RELEASE_LOCKED
```

Comando reproduzível:

```powershell
python -m pytest -q tests/product tests/test_t_frontend.py `
  tests/test_t_semantics_ir.py tests/test_t_workspace.py tests/test_t_tcap.py `
  tests/test_t_backend.py tests/test_t_metamorphosis.py tests/test_t_native.py `
  tests/test_semantic_scheduler.py
python tools/audit_public_artifact.py editions/casulo-public
```

## Vertical slice

`examples/t/product_memory.t` passa por lexer, parser, expression AST própria,
análise, IR/CFG, grafo, backends Python/C e artefato verificável. A execução
recebe `{"text":"lembra daquilo?"}` e retorna o mesmo texto. O artefato observado:

```text
artifact_id=sha256:7950afebe6a45048715bdae27c83a41eeb6c5e657efbc2eaae15c0da9da72da5
language=T/1.1
capability_requirements=[manifest]
```

TCAP 1.1 preserva requirements e rejeita capability desconhecida/duplicada;
nenhum grant é emitido. O corpus T/1.0 de 42 arquivos permanece congelado.

## Limites

- `Result` possui assinatura tipada, ainda sem construct/match;
- CFG existe sem SSA/phi;
- memória viva e effects de memória reais começam no Sprint 4;
- nenhuma dependência nova foi instalada;
- nenhum benchmark científico novo foi iniciado.
