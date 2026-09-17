# TS14 — rehearsal integrada inédita

## Resultado

`TS14_INTEGRATED_REHEARSAL_PASS` foi obtido na tentativa append-only
`product-demos/t85-sovereign-engine/ts14-integrated-rehearsal-attempt3`.

O ensaio carregou `casulo` e `casulo_owner` exclusivamente do aplicativo
empacotado em `release/t85-human-proof/OWNER_VM/app`. O processo foi iniciado
com `python -E`: `PYTHONPATH` não participou da resolução, mas o Python e as
dependências instaladas no host continuam sendo primitives declaradas.

## Pedido holdout

A ideia e os três requisitos HARD foram fornecidos somente pela CLI. Uma busca
literal em 209 arquivos textuais do aplicativo empacotado confirmou que eles
não estavam presentes antes da geração.

O Qwen3-4B local, por llama.cpp, produziu estocasticamente o agente
`ts14_mycelium_reconciler`. O TCAP resultante possui três módulos, onze funções
e hash
`ae3f65a1187fa46bef806799754faf875fc7d8279a3ab5ba104a0ae2aac1a8ea`.
O runtime Rust executou onze decisões do agente até `AUDITED`.

## Falha e reparo semântico

O primeiro candidato de evidência omitiu deliberadamente um dos três receipts
independentes. A autoridade T negou o fulfillment com
`hard_evidence_cardinality_mismatch`. O reparo anexou o receipt real ausente e
reexecutou toda a cadeia crítica; intent, capabilities, fulfillment e publish
produziram quatro receipts T e terminaram em `COMMIT`.

Essa é uma correção de evidência semântica, não um reparo neural do código-fonte.
O relatório não apresenta uma como se fosse a outra.

## Fluxo integrado observado

- projeto e constraint HARD foram persistidos via LivingMemory/DPAPI;
- o projeto foi fechado, reaberto e recuperado com proveniência;
- o Guia respondeu por inferência neural enquanto um job real de integridade
  permanecia em `STARTED`, seguido de evento autenticado `COMPLETED`;
- uma chamada sem grant de `simulation` foi negada por T e nenhum sentinel de
  efeito apareceu;
- a rota neural `intencao -> sinais -> engenharia` ativou bundles físicos e
  manteve subconjunto HOT estrito;
- Simulation Runtime executou apenas doubles, com zero efeito real;
- T decidiu `PREPARE -> SEAL -> PUBLISH`;
- o pacote v2 foi executado e serviu API loopback em diretório temporário fora
  do checkout, sem `PYTHONPATH`;
- importação, reedição, nova materialização, reboot e recall passaram;
- HOT voltou vazio depois do reboot.

O pacote v2 final do ensaio tem SHA-256
`23fe1d8e695b75fb4c848d569d83efed2c6d5b2ffbefe8558e95d23d6bc08f99`.

## Regressão

Foram aprovados 32 testes focais, cobrindo o harness e os subsistemas de
síntese, continuidade, presença, multiverso físico e materialização.

As tentativas 1 e 2 foram preservadas. A primeira mostrou que `python -I`
ocultava `psutil`; a segunda detectou um nome incorreto no novo coletor de
`JobEvent`. Nenhuma das duas é usada como prova do gate.

## Limites

- não é prova humana de Guilherme;
- não aprova química, voz física, utilidade ou design;
- não prova generalidade universal;
- Qwen3-4B, llama.cpp, Python, QEMU, drivers e kernels continuam primitives
  estrangeiras subordinadas às políticas T;
- Cloud segue `RELEASE_LOCKED`, rede guest `OFF`, USB/block devices proibidos,
  QPU negada e benchmark científico `NOT_STARTED`.
