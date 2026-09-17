# Casulo T85 — estado de execução

## Estado atual

```text
STATE=READY_FOR_GUILHERME_CASULO_T85_VM_HUMAN_PROOF
SPRINT=TS15
LAST_PASSING_GATE=TS15_RESEAL_HANDOFF_PASS
FAILED_GATE=NONE
```

Baseline: branch `product/semantic-multiverse`, commit
`df12e916c90d9bd2b966326275dc191573f38abd`, worktree preservado. Release RC13
permanece em `release/human-proof/` e não é alvo de overwrite.

## TS0

- pacote T85: 23/23 hashes PASS;
- baseline package/repo: conteúdo normalizado idêntico; line endings diferentes;
- matriz histórica 11 versus audit 9 registrada sem reclassificação;
- matriz T85 de 13 superfícies/65 pontos congelada;
- disco: 77,68 GiB livre; projected peak deixa 39,68 GiB;
- P0 abertos: 4; P1 ainda será inventariado no TS1;
- downloads/instalações: nenhum;
- Cloud/guest network/USB/QPU/scientific benchmark: locks preservados;
- human proof: não executada.

## TS1

- matriz executada: 13 superfícies/65 pontos;
- baseline honesto: `S_authority=0`, `S_execution=0`, `C_critical=0`,
  `P_authority=1`;
- nenhuma superfície RC4 estreita foi promovida ao caminho owner;
- `TDecisionReceipt` e medidor causal adicionados;
- mutation/bypass/anti-decoration: 6 testes PASS;
- P0 abertos: 4; nenhuma migração foi alegada neste gate.

## TS2

- frontend T/2.0 separado e compatível com T/1.0/T/1.1;
- tipos primitivos, records, enums, Option/Result e coleções limitadas;
- funções, state explícito, if/match, loops bounded, contracts e jobs;
- step/deadline/schema budgets obrigatórios;
- expression allowlist sem eval, shell, path ou chamada arbitrária;
- golden e negative corpus: 36 testes + 42 subtests PASS;
- autoridade permanece no baseline zero; TS2 não reivindica migração owner.

## TS3

- typed IR e bytecode funcional estruturado implementados;
- TCAP v2 possui 14 seções content-addressed e recompila source no verifier;
- runtime Rust produtivo emite `TDecisionReceipt` integral e falha fechado;
- conformance reference/Rust/Native: 5 casos normais + 1 exaustão PASS;
- malformed opcode, source/IR divergence, effect escalation, corrupção,
  schema futuro, cancel e budgets exercitados;
- regressão focal: 55 testes + 42 subtests PASS;
- Cargo runtime release offline PASS; Native/Cargo PASS;
- TCAP v1 Native padrão refeito depois do probe e G1–G3 PASS;
- duas tentativas falhas foram preservadas: target Cargo frio excedeu timeout e
  heap Native de 256 KiB esgotou; heap explícito passou a 2 MiB;
- limitação: T/2.0 Native roda no kernel do guest neste gate, não em ring 3;
- autoridade owner continua sem promoção: este sprint prova mecanismo, não uso.

## TS4

- standard library T/2.0: 13 módulos funcionais;
- vertical slice produtiva Rust: 13/13 módulos e receipts encadeados PASS;
- resultado: `SEALED`; effects solicitados: `simulation`, `manifest`;
- efeitos reais executados: zero;
- HARD desconhecido, project bleed, mutation e bypass falham fechados;
- regressão focal: 61 testes + 42 subtests PASS;
- ForeignBoundaryManifest criado com decisão estrangeira negada;
- nenhuma autoridade owner promovida neste sprint.

## TS5

- quatro autoridades críticas executadas por T/2.0 no runtime Rust produtivo;
- `material_intent`, `capabilities_effects`, `hard_requirement_fulfillment` e
  `publish_commit` possuem grau causal `d=1`;
- `C_critical=1`, `S_authority=29/65=0,446153846...`,
  `S_execution=0,446153846...`;
- 52 testes focais PASS, incluindo mutação, bypass, ausência de grant,
  `UNKNOWN`, cancelamento e efeito estrangeiro bloqueado;
- artefato limpo contém runtime, TCAP, sources, typed IR e transportes exatos;
- manifesto append-only: `0c1f61be3513e5a7970ec2bfd8d5bc67f887e40c64569d2afda12911e6a19768`;
- o probe é contratual e não foi apresentado como prova humana;
- nenhuma API externa, benchmark científico, Cloud, USB ou QPU foi ativado.

## TS6

- `HardFulfillmentInput` T é o aggregate canônico de RequirementGraph;
- `collect_evidence` produz fatos de verificadores sem campo de aceitação;
- evidence plans versionados usam tokens SHA-256 exatos, não substring;
- `FAIL`, `UNKNOWN`, evidence ausente, self-report e project bleed bloqueiam;
- 12 holdouts em quatro famílias foram congelados antes da geração e ficaram
  honestamente `BLOCKED` por ausência de evidência;
- cinco domain packs e um reparo arquitetural tiveram PASS por T;
- `FCR=0/6=0`, false HARD completion `0`, hard cases resolvidos ou bloqueados;
- regressão Einstein: candidato textual genérico bloqueado; kernel local 4D
  delimitado preservado, sem alegação de solver global;
- 69 testes focais PASS;
- manifesto append-only: `fb460970791d6f1dbfa0a3e9f52c224c0b8c49b4da96607dc7310c4a1fd287fb`.

## TS7

- três holdouts congelados geraram agentes T/2.0 distintos e multi-módulo por
  inferência Qwen3-4B local estocástica;
- 3 módulos, 11 funções e 11 receipts hosted por agente;
- nove requisitos HARD ligados a eventos canônicos derivados, sem permitir que
  a saída neural declare cumprimento;
- mutation, capability denial, fulfillment e publish T passaram;
- 3/3 casos tiveram observável e receipt lógico conformantes no Native/QEMU;
- imagem Native v1 padrão do RC13 foi restaurada ao final;
- regressão focal: 58 testes PASS;
- manifesto append-only: `3f346d0bcdc5d46099a25d4973cc6c92853f3420ca2a2a63041207cbdc6c7415`;
- seis tentativas anteriores/preflight foram preservadas e não contam como
  prova final; critical semantic loss do gate final: zero;
- human proof: `NOT_EXECUTED`.

## TS8

- launcher Semantic Multiverse usa `T85ContinuityService` com DPAPI;
- continuidade e memória são journalizadas em hash chain append-only;
- context selection é autorizada por policy T e gera receipt persistente;
- 500 turnos, 3 projetos, 501 decisions T, 515 eventos e 5 reboots PASS;
- constraints HARD perdidas: 0; project bleed: 0;
- conflito e recall ambíguo são explicitados, não escolhidos silenciosamente;
- single-writer, crash debris, supersession, compactação, export e consented
  delete cobertos;
- 50 testes focais PASS;
- manifesto append-only: `70eb6ac250d0568040e3c1178139bcb544c9a08141f294d7ad5c18af77b90baa`;
- limitação: reconstrução integral de projections por append tem custo crescente;
- voz física, química humana e design: `NOT_EXECUTED`.

## TS9

- `TurnCoordinator` T/2.0 integrado ao caminho owner;
- Presence e Work lanes independentes, com um worker e cancelamento;
- partial/final ASR, fallback textual, TTS streaming e frontend AEC exercitados;
- 120 turnos sintéticos de áudio + 20 turnos textuais em 60 minutos lógicos;
- 384 `TDecisionReceipt` encadeados;
- progresso não autenticado negado e conclusão tardia descartada;
- PCM bruto persistido: zero; dispositivos físicos abertos: zero;
- 41 testes focais PASS;
- manifesto append-only:
  `52ec4ab3771656747c3ce4a63120a8a6e799fd131514e6df7c72cfed53d1bb2d`;
- gate físico e qualidade da voz:
  `PENDING_GUILHERME_EXPLICIT_CONSENT` / `PROVISIONAL_OWNER_REVIEW_REQUIRED`.

## TS10

- seis `UniverseBundle` compactos, content-addressed e sem padding;
- mmap somente leitura, cache parseado, leases, sufficient state e reclaim;
- lifecycle físico autorizado pela policy T/2.0, com receipts T e foreign;
- perfis `REFERENCE_SIMPLE_RETRIEVAL`, `ALL_HOT` e `T_SPARSE_MULTIVERSE`;
- 180/180 campos críticos preservados; `L_critical=0`; project bleed=0;
- pico gerenciado sparse/all-hot: `5.342 / 28.642 = 0,18650932197472245`;
- mapped/cache após reclaim: zero;
- 36 receipts T + 36 foreign em cadeias verificadas;
- 19 testes focais PASS;
- manifesto append-only:
  `65dc705a9e6bce06d51ccf0e868ae2953af48272293ed6886638c5968dcb906f`;
- RSS total publicado sem target; Qwen/llama.cpp excluídos nominalmente;
- benchmark científico e claim energético: `NOT_STARTED`.

## TS11

- ciclo de materialização `PREPARE -> SEAL -> PUBLISH` decidido por T/2.0;
- cinco targets preservados, pacote v2 com runtime T/Rust e TCAP integral;
- agente Qwen holdout TS7, não trivial (3 módulos, 11 funções), executou fora do
  checkout com `PYTHONPATH` ausente;
- round-trip/reedição preservou CreationSpec, RequirementGraph, T source/IR/TCAP,
  capabilities/effects, evidências, proveniência e versão;
- 31 testes focais PASS;
- pacote v2 SHA-256:
  `cd6d2e5284084a76bb095fc7fe2b9fd7c12129a548b232e5a8c83aa602a09fb2`;
- manifesto append-only:
  `e1e0cb5c6bc1e076185ceb0552ab82d2d2433a464f12c0ae584c74fae7b9cc77`.

## TS12

- release owner T85 separado em `release/t85-human-proof/`; RC13 intacto;
- aplicação privada, T runtime e base VM empacotados; Qwen/llama.cpp localizados
  no cache owner por registry/hash sem duplicar pesos;
- checkout dependency=false; PYTHONPATH dependency=false;
- verifier e assinatura de desenvolvimento PASS;
- três ciclos limpos, restore ausente recuperável, snapshots, restore e crash
  recovery PASS a partir de cópia externa ao checkout;
- launchers VBS 4/4 parseados pelo Windows Script Host, `pyw.exe`, sem terminal;
- regressão focal: 15 PASS, 1 skip de symlink Windows ainda não contado;
- release manifest:
  `f10be0ad2f7022b001e1775ba9e6e91909db48ff1960ac8d85bb51d9f338dfb3`;
- evidence manifest:
  `34c8721e9cd297b5b4d7b5148c9e74c1b3fb9c055bc1672add7643323528d077`.

## TS13

- 51/51 arquivos llama.cpp iguais ao receipt de adoção;
- executável de 9.216 bytes explicado como PE launcher do
  `llama-server-impl.dll` de 10.064.384 bytes; version/commit conferidos;
- editions owner/public/cloud reconstruídas com boundaries distintos; public
  sem privados e Cloud `RELEASE_LOCKED`;
- attack probe, A/B update/rollback, downgrade, tamper, replay/cancel, prompt
  injection, grants, network/block devices, junction e ADS fail-closed;
- 64 mutações TCAP e 128 imports aleatórios rejeitados;
- 67 testes focais PASS; symlink físico único não executado por `WinError 1314`,
  explicitamente não contado como PASS;
- P0/P1 abertos no caminho suportado: zero;
- manifesto append-only:
  `c988d49d0f9a7f6697708ec13928b73317dff3594d18a168e830536c32207905`.

## TS14

- pedido micológico e três requisitos HARD recebidos somente por CLI e ausentes
  de 209 arquivos textuais do aplicativo empacotado;
- Qwen3-4B local estocástico gerou `ts14_mycelium_reconciler` sem seed fixa,
  API externa, fake, replay ou seleção de template fechado;
- agente T/2.0: 3 módulos, 11 funções, 11 receipts Rust e estado final `AUDITED`;
- evidência HARD incompleta negada por T; receipt independente ausente anexado e
  cadeia crítica reparada até `COMMIT`;
- retomada DPAPI, diálogo durante job, multiverso físico, simulação sem efeito,
  materialização, execução externa, import/reedit, reboot/recall e capability
  denial passaram;
- rota neural: `intencao -> sinais -> engenharia`; HOT vazio após reboot;
- pacote v2 do ensaio:
  `23fe1d8e695b75fb4c848d569d83efed2c6d5b2ffbefe8558e95d23d6bc08f99`;
- 32 testes focais PASS;
- manifesto append-only:
  `a3fb7af7ca0d796185e2236488867ac3a951052fc83170f40591fde1384222e1`;
- tentativas 1 e 2 preservam, respectivamente, isolamento excessivo de
  `psutil` e erro de campo no coletor; não contam como prova;
- human proof: `NOT_EXECUTED`.

## TS15

- candidato técnico TS12 preservado append-only em
  `release/t85-human-proof-superseded-ts12-technical-candidate/`;
- release final reconstruído em `release/t85-human-proof/`, com 215 arquivos,
  6.374.839 bytes e nenhum GGUF duplicado;
- manifest final:
  `87c046056ee16dbc2f02350f50bde62f9bb617ebfe002eb993536a794393f8ee`;
- `SHA256SUMS`:
  `1f897e9a9cd1e9e8bebb3d9e3ac05852e95d3655c7cfcc62cd6d2d3f12d723de`;
- assinatura SSH Ed25519 de desenvolvimento verificada; não é release comercial;
- produto: 448 PASS, 1 skip físico não contado; compilador/sistema: 73 PASS,
  1 skip físico não contado; Cargo/Native e Cargo T runtime PASS;
- appliance em cópia externa: 12/12 checks, três boots, snapshot/restore,
  crash recovery, base imutável e nenhuma dependência de checkout/PYTHONPATH;
- ataque final: 19 classes, P0=0, P1 suportado=0 e zero efeito não autorizado;
- owner/public/cloud reconstruídos e assinados separadamente; public com zero
  componente privado; Cloud `RELEASE_LOCKED`;
- matriz final: `S_authority=56/65=0,8615384615384616`,
  `S_execution=56/65=0,8615384615384616`, `C_critical=1,0`;
- superfícies sem crédito preservadas: tool composition, interface state e
  recovery/update;
- gate agregado: 34/34 checks PASS; primeiro fail do agregador preservado e
  corrigido sem reduzir critério;
- manifesto append-only TS15:
  `2b80a41dfa814f9920fdcbd3ac42a1b80173b35e9eb4354b5b5435d8ba4967b5`;
- espaço livre ao fechamento: 82.776.850.432 bytes;
- human proof, voz física, química, utilidade e design: `PENDING_GUILHERME`;
- benchmark científico/energético: `NOT_STARTED`.

## Próximo passo exato

Guilherme deve executar `release/t85-human-proof/START_CASULO_OWNER_T85.vbs`,
seguir `release/t85-human-proof/T85_HUMAN_PROOF_RUNBOOK.md` e registrar o
resultado com `release/t85-human-proof/COLLECT_T85_FEEDBACK.vbs`. Nenhum agente
automatizado está autorizado a aprovar a prova humana em seu lugar.
