# SPRINTS, GATES E ROADMAP DE FECHAMENTO

## 1. Horizonte

Estimativa de engenharia e validação: **80–180 horas**, altamente dependente de
lacunas reais de T, TTS/licenças, estabilidade da VM e falhas descobertas pelo
gate semântico. Tempo não aprova sprint; evidência aprova.

Estrutura append-only sugerida:

```text
product-demos/revolution-closure/
  rc00-baseline/
  rc01-contracts/
  rc02-guide/
  rc03-fulfillment/
  rc04-t-sovereignty/
  rc05-training/
  rc06-semantic-multiverse/
  rc07-vm/
  rc08-voice/
  rc09-materialization/
  rc10-security/
  rc11-integrated/
  rc12-release-candidate/
  rc13-handoff/
```

Todo `gate.json` contém:

```text
gate_id, status, baseline_commit, worktree_manifest_sha256,
machine_profile_sha256, commands, tool_versions, input_hashes,
output_hashes, model_adapter_hashes, sampling_policy,
test_summary, open_findings, authorized_claims,
forbidden_claims, timestamp, previous_gate_hash
```

## RC0 — Freeze, inventário e reconciliação

Entrega:

- baseline G10/SM/reseal/Einstein confirmado;
- estado humano anterior preservado como pendente;
- worktree e evidências congelados;
- Machine Profile/dependencies/disk/license inventory;
- branch/worktree seguro;
- smoke regressions read-only;
- Cloud/USB/QPU/campanha científica bloqueados.

Gate: `RC0_BASELINE_FROZEN`.

Falha: divergência, colisão, licença desconhecida ou reserva <25 GiB.

## RC1 — Constituição, métricas e trust boundaries

Entrega:

- schemas versionados de Guide, memory, requirements, evidence, jobs,
  capabilities, transport, materialization e update;
- threat model completo;
- thresholds pré-registrados por Machine Profile;
- severity P0/P1/P2;
- `S_T` weights congelados;
- holdout families seladas fora do contexto gerativo;
- claims permitidos/proibidos.

Gate: `RC1_CONTRACTS_TRUTH_AND_TRUST_PASS`.

## RC2 — Guia contínuo

Fecha item 1.

Entrega:

- GuideContinuityKernel/ConstraintLedger/DialogueDirector;
- memória por projeto e provenance;
- contradictions/open questions;
- Presence lane independente;
- configuração relacional reversível;
- retomada vaga “lembra daquilo?”;
- reboot/multi-project.

Testes:

- sessões sintéticas >=2h;
- três projetos intercalados;
- 20 memórias plantadas;
- 8 contradições;
- 10 ambiguidades;
- job longo + barge/cancel/restart;
- elogio automático/pressão/progresso falso adversarial.

Invariantes:

```text
mandatory_constraint_recall = 100%
cross_project_hard_leaks = 0
silent_material_commits = 0
job_claims_without_receipt = 0
unconfirmed_overwrites = 0
stereotype_driven_adaptation = 0
```

Gate: `RC2_GUIDE_COLLEAGUE_LOOP_PASS`.

Química permanece `PENDING_GUILHERME`.

## RC3 — RequirementGraph e fulfillment

Fecha item 2.

Entrega:

- decomposition/RequirementGraph;
- EpistemicGate/DomainPack;
- evidence planning e heterogeneous verifiers;
- false-completion detector;
- architecture repair;
- explicit partial/refusal states;
- holdouts em ao menos cinco domínios;
- aplicação completa, não só script.

Gate:

```text
hard_requirements_without_evidence = 0 em PASS
false_completion_on_decoys = 0
unsupported_tasks_honestly_refused = 100%
known_semantic_gap_hidden = 0
transactional_failure_preserves_previous = true
```

Gate: `RC3_SEMANTIC_FULFILLMENT_PASS`.

## RC4 — T soberana

Fecha item 3.

Entrega:

- gap audit e RFCs;
- IR/contracts/effects/jobs/memory/tools/materialization T;
- ForeignBoundaryManifest;
- incremental invalidation;
- T packages/lock/SBOM;
- migração strangler sem rewrite total.

Gate:

```text
S_T >= 0.80
critical_capability_decisions_T = 100%
materialized_behavior_has_T_origin = 100%
foreign_boundaries_manifested = 100%
implicit_effects = 0
```

Gate: `RC4_T_SOVEREIGN_CREATION_PASS`.

## RC5 — Data Foundry e camada aprendida Casulo

Fecha item 4 dentro do limite honesto.

Entrega:

- registry/cards/lineage;
- consent/redaction/dedup/splits;
- SFT/preference/T/router schemas;
- baseline e holdout congelados;
- treino real de router/classifier ou especialista pequeno;
- adapter load/disable/rollback;
- uso real em uma rota;
- 4B LoRA apenas se hardware gate passar.

Gate:

- artifact aprendido first-party real;
- ganho >= epsilon pré-registrado;
- zero leakage e regressão crítica;
- base fallback funciona;
- hashes/licença/card completos;
- ausência do adapter nunca amplia capability.

Gate: `RC5_CASULO_FIRST_PARTY_LEARNED_LAYER_PASS`.

Estados auxiliares honestos:

```text
CASULO_4B_ADAPTER=DEFERRED_COMPUTE_NOT_AVAILABLE
DPO=NOT_JUSTIFIED_YET
```

Eles não invalidam o layer first-party menor; devem permanecer nas claims.

## RC6 — Semantic Multiverse validado

Fecha item 5.

Entrega:

- partition/route/lifecycle/thermostat;
- exact vs derived content;
- sufficient-state contracts;
- dedup/delta/quota/compaction/forget;
- reference/simple retrieval/multiverse profiles;
- long-session growth, pressure, thrashing, corruption, reboot.

Gate absoluto:

```text
mandatory_constraint_loss = 0
cross_project_bleed = 0
corrupt_blob_used = 0
unexplained_duplicate_growth = 0
late_cancelled_publish = 0
```

Também: working set HOT estrito com `N>=6`, budget respeitado, freeze/thaw
crítico preservado e vantagem descrita apenas no workload observado.

Gate: `RC6_SEMANTIC_MULTIVERSE_PRODUCT_VALIDATION_PASS`.

## RC7 — Appliance VM one-click

Fecha item 6.

Entrega:

- launcher sem console;
- doctor/estimation/recovery humanos;
- immutable base + owner overlay/data/exchange;
- HostAcceleratorService estreito;
- snapshot/restore/crash recovery;
- terminal somente técnico;
- guest network off.

Gate:

- duplo clique abre Casulo;
- zero PowerShell manual no fluxo normal;
- zero traceback bruto;
- três ciclos launch/create/shutdown/restart;
- base hash imutável;
- exchange confinado;
- engine missing/incompatible recuperável;
- update inválido recusado.

Gate: `RC7_OWNER_VM_ONE_CLICK_PASS`.

## RC8 — Voz primária

Fecha item 7 até a fronteira de prova humana.

Entrega:

- device profiles/calibration;
- AEC/NS/AGC/VAD/ASR pt-BR;
- full duplex/barge-in;
- TTS streaming local e cadeia redistribuível auditada;
- VoiceProfile;
- Presence durante jobs;
- synthetic/loopback suite;
- físico apenas com consentimento.

Gate automatizado: `RC8_VOICE_PRIMARY_IMPLEMENTATION_PASS`.

Para selo final, não pode existir falha física P1 já conhecida no dispositivo
de Guilherme. Se a prova física só ocorrer na sessão final, marcar:

```text
PHYSICAL_VOICE_HUMAN_VALIDATION=PENDING
```

sem chamá-la de PASS.

## RC9 — Materialização externa e round-trip

Fecha item 8.

Entrega:

- `.casulo`, CLI/exe, API loopback, service e desktop/web matrix;
- target compatibility;
- runtime closure;
- clean-environment harness;
- import/edit/export v2;
- manifests/SBOM/hashes/signature;
- secret slots/sandbox/logs.

Gate:

- todos os targets prometidos executam sem repo/PYTHONPATH/cache;
- critical round-trip invariants = 1;
- real effects during tests = 0;
- secrets in payload = 0;
- validated bytes = published bytes;
- previous version recoverable;
- public permanece sem owner.

Gate: `RC9_EXTERNAL_MATERIALIZATION_MATRIX_PASS`.

## RC10 — Ataque integrado

Fecha item 9 e audita RC2–RC9.

Campanhas:

- prompt/memory/domain injection;
- capability/confirmation bypass;
- command/path/symlink/archive attacks;
- IPC replay/spoof/version/frame limits;
- codegen malicioso;
- cancellation/crash races;
- secret/log leakage;
- update tamper/downgrade;
- manifest/payload mismatch;
- owner/public/cloud boundary;
- network/USB/device denial;
- bounded fuzzing.

Gate:

```text
P0 = 0
P1_on_supported_human_path = 0
private_in_public = 0
secret_findings = 0
unauthorized_real_effects = 0
invalid_updates_accepted = 0
```

Gate: `RC10_SECURITY_TRUST_PASS`.

## RC11 — Ensaio prolongado integrado

Em overlay limpo:

1. iniciar por um clique;
2. reabrir memória;
3. criar/alternar três projetos;
4. introduzir contradições;
5. iniciar holdout inédito;
6. conversar durante geração;
7. interromper e mudar requisito;
8. induzir gap “compila mas não cumpre”;
9. reparar arquitetura;
10. simular/materializar em targets;
11. executar fora do repo;
12. importar/editar/exportar v2;
13. reiniciar e confirmar HOT vazio;
14. reidratar;
15. crash/restore;
16. verificar crescimento/quotas/hashes.

Gate: `RC11_INTEGRATED_HUMAN_PROOF_REHEARSAL_PASS`.

Não avaliar química em nome de Guilherme.

## RC12 — Release candidate owner

Entregas:

```text
release/human-proof/
  START_CASULO_OWNER.exe-or-equivalent
  VERIFY_RELEASE.exe-or-equivalent
  RESTORE_CLEAN_STATE.exe-or-equivalent
  COLLECT_FEEDBACK.exe-or-equivalent
  OWNER_VM/
  MANIFEST.json
  SBOM.spdx.json
  SHA256SUMS
  DEVELOPMENT_SIGNATURE.json
  HUMAN_PROOF_CARD.md
  HUMAN_PROOF_RUNBOOK.md
  KNOWN_LIMITATIONS.md
  CLAIMS.md
  ROLLBACK.md
```

Rebuild em staging limpo, três boots, restore, voz sintética, materialização,
auditorias e suíte integral.

Gate: `RC12_HUMAN_PROOF_CANDIDATE_SEALED`.

## RC13 — Handoff e parada

Entregar comando/atalho exato, snapshot limpo, runbook curto e coletor de
feedback. Registrar espaço, hashes, limitações e próximos estados.

Estado final:

```text
READY_FOR_GUILHERME_CASULO_BETA_HUMAN_PROOF
```

Nunca declarar `GUILHERME_HUMAN_PROOF_PASS` antes da sessão.

## Dependências entre sprints

```text
RC0 -> RC1
RC1 -> RC2, RC3, RC4
RC2+RC3+RC4 -> RC5
RC2..RC5 -> RC6
RC6 -> RC7 -> RC8
RC3+RC4+RC7 -> RC9
RC2..RC9 -> RC10 -> RC11 -> RC12 -> RC13
```

Implementação pode paralelizar subtarefas, mas selos seguem essa ordem.

## Política de checkpoint

Qualquer gate falho:

```text
STATE=IN_PROGRESS_CHECKPOINTED
LAST_PASSING_GATE
FAILED_GATE
EXACT_FAILURE
EVIDENCE_PATHS
FILES_CHANGED
FILES_PRESERVED
SAFE_NEXT_COMMAND
USER_AUTHORITY_REQUIRED
SPACE_REMAINING
```

Não desfazer gates aprovados, não reduzir critérios depois do resultado e não
usar `PASS_WITH_RISK` para P0/P1.

