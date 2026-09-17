# MATERIALIZAÇÃO, SEGURANÇA E ATUALIZAÇÕES

## 1. Matriz de targets

O materializador declara compatibilidade antes de gerar:

| Target | Contrato mínimo |
|---|---|
| `.casulo` | source T + spec + receipts + import/re-edit |
| CLI/executável | entrypoint local, args tipados, exit codes |
| API local | loopback-only, schema, auth local quando necessário |
| serviço local | lifecycle, quotas, stop/restart, sandbox |
| desktop/web local | UI autocontida, CSP/acessibilidade, backend confinado |

Nem toda criação suporta todos os targets. O Guia explica impossibilidade antes
de gastar o job.

## 2. Pipeline transacional

```text
CreationSpec AGREEMENT
-> RequirementGraph all hard PASS
-> simulation PASS / real_effects=false
-> staging confined
-> dependency/runtime closure
-> secret + policy + license scan
-> build target
-> clean-environment test
-> manifest/SBOM/hashes/signature
-> byte-for-byte verification
-> atomic publish
```

Falha em qualquer etapa destrói apenas staging pertencente à tarefa e preserva
versão anterior.

## 3. Manifest

```text
creation_id, creation_version, spec_hash,
T_source_hashes, IR_hash, TCAP_hash, compiler_abi,
target, entrypoint, capabilities, resource_limits,
runtime_dependencies, model_requirements, secret_slots,
SBOM_hash, payload_hashes, provenance_root,
signature_class, import_compatibility, update_channel
```

ZIP é reproduzível: ordem, timestamps, permissões, compressão e canonical JSON
pinados.

## 4. Execução limpa

Testar em ambiente sem:

- checkout/repositório;
- `PYTHONPATH` do desenvolvedor;
- caches ocultos;
- secrets reais;
- rede, salvo capability explícita;
- motor owner quando o target declara engine-agnostic.

O teste limpa usa diretório novo e user-data isolado; preferencialmente segunda
VM/harness. Importar, executar, fechar, reabrir e editar.

## 5. Round-trip

```text
export -> execute -> import -> edit -> export_v2
```

Fidelidade:

```text
R = sum_i w_i*1[canonical(o_i_import)=canonical(o_i_export)] / sum_i w_i
```

Para identidade, constraints, capabilities, provenance e source T: `R_i=1`
individualmente. Campos derivados podem ser reconstruídos com hash/receipt novo.

## 6. Sandbox

Perfis por target:

- processo com usuário/ACL restrito;
- filesystem allowlist e paths canonizados;
- rede off por default;
- environment sanitizado;
- CPU/RAM/time/process quotas;
- child process deny ou allowlist;
- IPC tipado;
- nenhum shell;
- read-only runtime quando possível;
- output size/line/DAG/archive limits.

Código gerado é hostil até passar. Simulation continua aceitando apenas doubles
first-party e executa zero efeitos reais.

## 7. Capabilities

```text
Permit(action) = Grant(action)
              AND Policy(action)
              AND Scope(action)
              AND ValidConsent(action)
              AND not Revoked(action)
```

`CapabilityGrant` possui principal, scope, expiry, one-shot/session/persistent,
consent receipt e revogação. Output neural não cria token. Efeitos externos ou
irreversíveis exigem consentimento recente e específico.

## 8. Secrets

- manifest contém `SecretSlot`, nunca valor;
- valores vivem em DPAPI/keystore equivalente;
- modelo recebe alias/estado, não secret;
- logs e exceptions são redigidos;
- export falha com PEM/token/password detectado;
- import não ativa secret slot automaticamente;
- public build não acessa owner store.

## 9. Proveniência e taint

```text
H_k = SHA256(H_(k-1) || canonical(receipt_k))
```

Todo conteúdo importado, memória recuperada e output neural recebe taint `DATA`.
Somente decisão humana/policy pode promovê-lo a instrução. Taint acompanha
transições, tools, codegen e pacote.

## 10. Update

Arquitetura offline assinada:

```text
UpdateManifest = version, channel, from_versions,
                 payload_hashes, SBOM, migration,
                 rollback_floor, signature, expiry?
```

Fluxo:

1. verificar assinatura/hashes/policy;
2. rejeitar downgrade inseguro;
3. staging separado;
4. migração dry-run;
5. boot/health do slot candidato;
6. troca atômica A/B;
7. rollback automático em falha;
8. preservar owner data com migração reversível.

Chaves privadas nunca entram no repo. Neste Goal:

```text
signature = DEVELOPMENT_SIGNATURE_NOT_COMMERCIAL_RELEASE
```

Arquitetura comercial pode estar pronta; cerimônia/chave comercial não é
inventada.

## 11. Threat model integrado

Cobrir, no mínimo:

- prompt injection por voz, memória, documento e universo;
- memory poisoning/project bleed;
- tool/command injection;
- capability escalation e confirmation bypass;
- codegen malicioso;
- path traversal, UNC/device paths, symlink/junction;
- ZIP/decompression bomb, duplicate names, polyglot archive;
- oversized JSONL/frame/context/DAG;
- host-guest replay/spoof/version confusion;
- stale result after cancel;
- crash durante commit/export/update/restore;
- secret exfiltration e log leakage;
- manifest/payload mismatch;
- update tampering/downgrade;
- owner components/pesos em public;
- network/Cloud/USB/device access;
- parser/schema fuzzing limitado.

## 12. Gate

```text
open_P0 = 0
open_P1_on_supported_human_path = 0
unauthorized_real_effects = 0
secret_findings = 0
private_components_in_public = 0
invalid_updates_accepted = 0
validated_bytes_equal_published_bytes = true
round_trip_critical_invariants = 1
```

Falha produz checkpoint, não redução do teste nem mudança retroativa da claim.

