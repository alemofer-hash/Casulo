# Evidência — Sprint 11 Casulo Cloud standby

Data: 2026-08-11

Estado: `SPRINT_11_CLOUD_STANDBY_PASS_RELEASE_LOCKED`

## Entrega

O serviço privado standby implementa protocolo engine, autenticação abstrata com
adapter exclusivamente de teste, policy deny-by-default, job broker limitado,
backpressure, cancelamento, idempotência, replay protection e observabilidade
sem conteúdo do usuário.

O target não possui servidor de produção. `production_bind` falha sempre com
`RELEASE_LOCKED`, inclusive quando ambiente ou identidade tentam simular uma
liberação. Não foram criados DNS, credenciais, endpoint, deploy ou segredo real.

O cliente público continua contendo somente `CloudEngineClient`; sem harness ele
falha honestamente e nunca procura o motor owner.

## Reprodução

```powershell
$env:PYTHONPATH = 'src;services/casulo-cloud-standby/src;editions/casulo-public/src;private/casulo-owner/src'
python -m casulo_cloud_standby.demo
python -m pytest tests/product/test_engine_boundary.py -q
python tools/audit_public_artifact.py editions/casulo-public
```

A demo exige simultaneamente replay idempotente exato e negação do bind de
produção para retornar sucesso. Nenhum benchmark científico foi iniciado.
