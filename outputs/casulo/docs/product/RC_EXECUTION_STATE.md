# Estado de execução — Casulo Revolution Closure

- Estado: `READY_FOR_GUILHERME_CASULO_BETA_HUMAN_PROOF`
- Sprint corrente: `RC13` concluído e resselado; handoff humano pendente
- Último gate técnico aprovado: `RC13_HANDOFF_COMPLETE_VBSCRIPT_RESEAL`
- Gate SHA-256: `2d2de97b0d0d574a18d99274b9080d212dd159930dc552d821eba98332273c79`
- Branch: `product/semantic-multiverse`
- Commit baseline: `df12e916c90d9bd2b966326275dc191573f38abd`
- Worktree preexistente: preservado, substancialmente modificado
- Machine Profile SHA-256: `7ca1b196f47eb6e20769ae165c1b1a322d9f9abdd2ebc3dc4a7201acff8dd718`
- Modelo bootstrap: Qwen3-4B Q4_K_M, hash verificado
- Runtime bootstrap: llama.cpp b10362, hash verificado
- Download/instalação neste Goal: `0`
- Espaço livre no RC0: 83.666.690.048 bytes
- Espaço livre no selo RC12: 83.575.582.720 bytes (`77,84 GiB`)
- Espaço livre após o resselamento RC13: 83.539.959.808 bytes (`77,80 GiB`)
- Pacote owner: `release/human-proof/`, 2,42 MiB sem duplicar pesos
- Manifest SHA-256: `b6bfaa8166b0b2174392be64c1936a266e8a8cd119c9c7a8ab5e38017c2c4196`
- Launcher `START_CASULO_OWNER.vbs`: `bb5d0759ce664b812e3dd66dcc50c984d02273789040a868eb4b8a1419c5ceea`
- Errata: o candidato anterior usava BOM UTF-8 incompatível com o WSH do host;
  foi preservado em `release/human-proof-superseded-vbscript-utf8-bom-attempt2/`.
- Regressão do launcher: quatro `.vbs` executados pelo `cscript.exe` real,
  `4/4` com exit code zero e `CASULO_VBS_PARSE_PASS`; `5 passed` no foco.
- Próximo passo exato: Guilherme abre `release/human-proof/VERIFY_RELEASE.vbs` e depois `START_CASULO_OWNER.vbs`

## Fechamento RC3–RC12

- RC3: cinco domínios holdout com Qwen local real e evidência independente;
- RC4: soberania T `S_T=1,0` nas nove superfícies congeladas;
- RC5: roteador first-party promovido, 1,00 contra baseline 0,25 no conjunto declarado;
- RC6: working set Semantic Multiverse estrito e quatro perfis reais;
- RC7: appliance owner, três boots, snapshots, restore e crash recovery;
- RC8: ASR local e voz sintética/cancelável; prova física permanece humana;
- RC9: cinco targets externos, assinatura e round-trip em clean-room;
- RC10: campanha de ataque limitada com zero P0/P1 no caminho suportado;
- RC11: criação neural inédita, reparo por diagnostic e ensaio integrado;
- RC12: candidato assinado, 343 testes de produto + 73 de compilador/sistema,
  dois skips declarados, Cargo PASS e três boots da base empacotada.

## Evidência RC0

- pacote: 22/22 hashes, cobertura exata, zero membro inseguro;
- G10: 4/4 hashes preservados;
- reseal/Einstein: 4/4 hashes preservados;
- doctor neural: PASS;
- doctor Semantic Multiverse: PASS;
- doctor VM: PASS;
- public source audit: PASS, 12 arquivos, zero privado;
- smoke focal: 8 passed;
- tentativa ambiental anterior preservada, não reclassificada.

Artefatos: `product-demos/revolution-closure/rc00-baseline-attempt2/`.

## Evidência RC1

- nove schemas fechados e versionados;
- RequirementGraph com HARD/SOFT, UNKNOWN e evidência independente;
- authority conjunctiva e taint DATA/INSTRUCTION;
- thresholds e pesos S_T pré-registrados;
- cinco famílias holdout seladas fora do contexto gerativo;
- threat model e severidade P0/P1/P2;
- regressão focal: 33 testes aprovados.

Artefatos: `product-demos/revolution-closure/rc01-contracts/`.

## Evidência RC2

- kernel canônico, ledger de constraints e DialogueDirector implementados;
- ensaio sintético: 7.200 s, 3 projetos, 121 turnos, 13 interrupções e 3 jobs;
- zero project bleed, zero perda de constraint e zero progresso inventado;
- contradição HARD bloqueou até decisão humana; decisões rejeitadas persistiram;
- reboot reconstituiu estado idêntico por hash chain;
- Qwen local real recebeu a diretiva tipada e passou memória/rede/job sem fake/API;
- duas falhas de oráculo lexical foram preservadas; regressões semânticas corrigiram o juiz;
- regressão focal final: 23 testes aprovados.

Artefatos: `product-demos/revolution-closure/rc02-guide/`.

## Fronteiras invariantes

```text
Cloud=RELEASE_LOCKED
guest_network_default=OFF
USB/block_devices=PROHIBITED
QPU=UNAVAILABLE_DENY
scientific_benchmark=NOT_STARTED
signature=DEVELOPMENT_NOT_COMMERCIAL
human_chemistry_voice_design_approval=PENDING_GUILHERME
```

## Claims não autorizados

- prova humana concluída;
- voz, química ou design aprovados por Guilherme;
- release comercial;
- foundation model próprio treinado do zero;
- compressão universal, datacenter em 32 GB ou capacidade quântica;
- superioridade científica, energética ou universal.
