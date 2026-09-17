# REGISTRO DE RISCOS E REGRAS DE PARADA

## Severidade

### P0 — bloqueia selo

- perda/corrupção de criação, memória, baseline ou base VM;
- efeito real sem grant e confirmação;
- escape de sandbox/guest/path;
- secret ou conteúdo owner no public;
- hash/signature/update inválido aceito;
- rede guest/Cloud/USB habilitados silenciosamente;
- cross-project bleed de constraint/fato obrigatório;
- falso semantic PASS;
- bytes publicados diferentes dos validados;
- traceback fatal no fluxo humano;
- output neural construindo shell/comando;
- treino com conteúdo owner sem consentimento;
- claim falso de autoria, físico, científico ou comercial.

### P1 — bloqueia caminho humano suportado

- função central apenas por terminal;
- voz indisponível no hardware declarado;
- barge-in não interrompe;
- exploração vira compromisso sem confirmação;
- contradição dura não é detectada;
- conversa bloqueia por job;
- recuperação exige conhecimento do repo;
- export só roda dentro da árvore;
- reparo mantém desvio semântico conhecido;
- reedição perde provenance/constraints;
- bridge host/guest falha aberta.

### P2

Fricção/capricho que não impede jornada e fica no backlog de Guilherme.

## Matriz

| ID | Risco | Controle / gate |
|---|---|---|
| R01 | memória inventada | provenance, confidence, margin/clarification |
| R02 | projetos misturados | project namespace + hard isolation tests |
| R03 | bajulação/pressão | profile dimensions + adversarial dialogue suite |
| R04 | progresso falso | Presence somente de JobEvent |
| R05 | compila mas não cumpre | RequirementGraph + independent evidence |
| R06 | teste tautológico | heterogeneous verifier + holdout |
| R07 | repair infinito | bounded budget + honest terminal state |
| R08 | lógica crítica fora de T | sovereignty matrix + FFI manifest |
| R09 | métrica S_T manipulada | weights congelados no RC1 |
| R10 | treino 4B inviável | hardware gate + small specialist path |
| R11 | dataset contaminado | family split + dedup + lineage |
| R12 | dados pessoais nos pesos | consent/redaction/owner separation |
| R13 | adapter piora segurança | per-dimension promotion + rollback |
| R14 | router neural autoriza efeito | deterministic capability broker |
| R15 | FROZEN perde constraint | exact/derived split + zero-tolerance probes |
| R16 | thrashing | hysteresis, leases, residence, quotas |
| R17 | disco cresce sem limite | delta/dedup/quota/compaction receipts |
| R18 | claim datacenter/quantum | claim policy e gate editorial |
| R19 | VM ainda parece tooling | one-click acceptance, zero console |
| R20 | bridge host frágil | versioned authenticated bounded RPC |
| R21 | ASR interfere em barge-in | acoustic stop separado de semantics |
| R22 | AEC destrói near-end | double-talk/device physical gates |
| R23 | licença TTS incompatível | full dependency/voice/G2P ledger |
| R24 | export depende do repo | clean-environment harness |
| R25 | secret no pacote | slots + scanner + keystore |
| R26 | artifact malicioso | sandbox + untrusted import/codegen |
| R27 | update comprometido | signed A/B staging + rollback floor |
| R28 | public vaza owner | exact allowlist + source/wheel/package audit |
| R29 | worktree do usuário perdido | freeze, no reset/clean/add-all |
| R30 | 80 GiB consumidos | peak projection + 25 GiB reserve |

## Stop rules

Interromper a trilha afetada quando:

- baseline/hash divergir;
- mutation colidir com trabalho preexistente;
- projected free after peak <25 GiB;
- download/instalação/áudio/compute exigir consentimento ausente;
- licença/origem/hash não fechar;
- treino exceder RAM/VRAM/cooling seguro;
- holdout estiver contaminado;
- restrição obrigatória for perdida;
- rollback não existir;
- P0 aparecer;
- P1 impedir o roteiro final;
- dependencia private/R&D vazar em public;
- ação exigir rede guest, Cloud, QPU, USB ou block device;
- TTS funcionar tecnicamente mas não tiver cadeia redistribuível auditável.

## Resposta a bloqueio

1. parar somente a ramificação;
2. preservar todos os gates passados;
3. não alterar threshold/claim;
4. registrar evidência e diff;
5. continuar trabalho independente seguro;
6. entregar:

```text
STATE=IN_PROGRESS_CHECKPOINTED | BLOCKED_*
LAST_PASSING_GATE
FAILED_GATE
EXACT_FAILURE
EVIDENCE_PATHS
FILES_CHANGED
FILES_PRESERVED
SAFE_NEXT_COMMAND
AUTHORITY_OR_RESOURCE_REQUIRED
SPACE_REMAINING
```

`PASS_WITH_RISK` não é permitido para P0, P1, licença, consentimento ou evidência
física ausente.

## Estados finais permitidos

```text
READY_FOR_GUILHERME_CASULO_BETA_HUMAN_PROOF
IN_PROGRESS_CHECKPOINTED
BLOCKED_BASELINE_DIVERGENCE
BLOCKED_WORKTREE_COLLISION
BLOCKED_DISK_BUDGET
BLOCKED_EXPLICIT_CONSENT
BLOCKED_LICENSE
BLOCKED_TRAINING_COMPUTE
BLOCKED_PHYSICAL_VOICE
BLOCKED_ENVIRONMENT
```

