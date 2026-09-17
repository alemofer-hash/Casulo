# Evidência — Sprint 6 Guide Presence

Data: 2026-08-11

Estado: `SPRINT_6_GUIDE_PRESENCE_PASS`

## Vertical slice executável

`GuidePresence` mantém diálogo em `EXPANSION` ou `CRYSTALLIZATION` sem possuir
nem bloquear workers. Um evento de voz `PRESENCE` preempta o evento de job; o
job continua ativo e seu progresso só aparece depois que um `JobEvent` canônico
com timestamp, proveniência e SHA-256 de evidência é aceito.

O Hosted Shell demonstrou a ordem:

```text
VOICE -> GUIDE_JOB_EVENT
```

com a criação em `FIRST_INTENT`, o Guia ainda responsivo e o job de fundo
ativo. O milestone usado na demonstração possui SHA-256
`b91fbda041f6b4c1717f296c52ecc30df00125f770e38980b84732742ccc9460`.

## Restrições aprovadas

- fala parcial nunca cristaliza intenção;
- ambiguidade produz esclarecimento, não preenchimento silencioso;
- adaptação só é aplicada com evento e aprovação humana explícita;
- pressão maior que zero não pode ser proposta pelo Guia;
- atributos fora do contrato individual são rejeitados;
- conflitos são explicitados em vez de concordância automática;
- eventos de job exigem hash real, ordem monotônica e terminalidade;
- progresso livre sem receipt não entra no caminho novo do Guia.

## Comandos

```powershell
python -m pytest tests/product/test_guide_presence.py `
  tests/product/test_hosted_shell.py tests/product/test_living_memory.py -q
python -m casulo.product.hosted_demo --utterance `
  "Quero um Guia local que preserve minha intenção e continue presente."
```

Resultado focal: `20 passed` e demonstração `ok=true`.

O Sprint não implementa `IntentDelta`; essa fronteira permanece reservada ao
Sprint 7. Nenhum modelo generativo recebe autoridade para progresso, grants ou
preferências. Nenhum benchmark científico novo foi iniciado.
