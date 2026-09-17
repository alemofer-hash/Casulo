# Arquitetura vinculante — Revolution Closure

## Autoridade

```text
fala/arquivo/memória externa (DATA não confiável)
  -> modelo neural local propõe
  -> contratos tipados validam
  -> RequirementGraph separa obrigações
  -> verificadores independentes produzem EvidenceReceipts
  -> T decide intent/capability/publish
  -> CapabilityBroker aplica grant + policy + scope + consent - revoke
  -> simulation/sandbox
  -> publicação atômica dos mesmos bytes validados
```

O modelo pode escolher texto, hipóteses, rotas candidatas e código candidato.
Ele não concede capabilities, converte dado em instrução, confirma intenção,
declara evidência independente, publica ou assina.

## Planos

- `Guide plane`: Presence, continuidade, memória por projeto e jobs reais.
- `Fulfillment plane`: RequirementGraph, domain packs, verificação heterogênea,
  gaps e reparo arquitetural.
- `T plane`: AST/semântica/IR/grafo/TCAP, effects, ForeignBoundaryManifest e
  decisões críticas.
- `Learned plane`: Qwen bootstrap declarado + pequenos adapters/classifiers
  first-party versionados; política determinística permanece autoridade.
- `Semantic Multiverse`: catálogo, router, sufficient state, lifecycle e store
  content-addressed.
- `Appliance plane`: VM imutável, overlay owner, RPC local autenticada, voz e
  renderer derivados de eventos.
- `Materialization plane`: pacote v2, runners externos, SBOM, hashes,
  round-trip e update A/B.

## Fronteiras de edição

`casulo-owner` acessa o motor privado diretamente. `casulo-public` contém apenas
o cliente Cloud e nunca recebe motor, pesos, adapters owner ou fallback local.
`casulo-cloud-standby` permanece compilável/testável e `RELEASE_LOCKED`.

## Evidência

Compilar é apenas uma classe de evidência. Aceite exige todos os requisitos
HARD em PASS por verificadores nomeados e independentes, safety PASS e zero
claim não suportado. Média ou autoavaliação neural não compensam falha dura.

