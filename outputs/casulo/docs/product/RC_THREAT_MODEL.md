# Threat model — Revolution Closure

## Ativos

Motor owner, pesos/adapters, memória e criações de Guilherme, fontes T/TCAP,
secrets, grants, manifests, chaves de assinatura, overlay/base VM e pacote
public.

## Adversários e entradas

- conteúdo importado com prompt injection;
- output neural malformado, hostil ou alucinado;
- pacote/manifest/TCAP/update adulterado;
- replay, duplicação, cancelamento tardio e troca de bytes após validação;
- arquivo, symlink, path traversal, zip bomb ou parser exhaustion;
- processo guest tentando rede, clipboard, shared folder, USB ou disco host;
- vazamento owner para build public;
- job que inventa progresso ou cruza projeto;
- dependência/licença não auditada.

## Trust boundaries

Todo conteúdo importado ou gerado entra como `DATA`. Promoção para
`INSTRUCTION` exige schema, policy e capability determinísticos. O modelo não
cria grant, approval, secret, assinatura ou evidência independente.

Efeitos são deny-by-default. A permissão é conjunção de grant, policy, scope e
consentimento válido, sem revogação. Publicação assina exatamente os bytes
validados e usa troca atômica.

## Controles absolutos

- secrets fora de artifacts/contexto;
- rede guest OFF e Cloud RELEASE_LOCKED;
- USB, block device e QPU negados;
- sandbox/quotas/timeout/cancelamento;
- base VM read-only, overlay confinado;
- parsers com limites e quarentena;
- CI falha se public contiver privado;
- update offline assinado, A/B e rollback;
- logs/telemetria sem conteúdo do usuário por padrão.

P0 e P1 no caminho suportado não aceitam `PASS_WITH_RISK`.

