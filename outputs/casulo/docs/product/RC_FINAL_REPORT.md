# Relatório final — Casulo Revolution Closure

## Resultado

RC0–RC12 foram aprovados e o RC13 entregou o handoff. Estado:
`READY_FOR_GUILHERME_CASULO_BETA_HUMAN_PROOF`.

O candidato integra Guia contínuo, RequirementGraph e fulfillment independente,
T soberana nas superfícies congeladas, roteador aprendido first-party, Semantic
Multiverse, appliance VM, voz local, materialização externa e controles de
segurança. A criação neural de RC11 usou Qwen local real, reparou uma falha de
fulfillment por diagnostic e não utilizou fake engine nem API externa.

## Validação final

- produto: 343 passed, 1 skipped;
- compilador/sistema: 73 passed, 1 skipped;
- Cargo/Native: PASS;
- base empacotada: três boots, restore e crash recovery PASS;
- voz: ASR sintético + TTS first-party/cancelamento PASS, sem dispositivo físico;
- materialização: pacote, CLI, API, serviço e desktop-web em clean-room PASS;
- owner: allowlist exata, sem fake/API/pesos embutidos;
- public: zero componente privado na fonte e no wheel;
- Cloud: `RELEASE_LOCKED` e production ineligible;
- segurança: zero P0/P1 automatizado no caminho suportado.

## Limites

Qwen3-4B é bootstrap Apache-2.0; llama.cpp é runtime MIT. O roteador Casulo é
pequeno e de escopo restrito. Inferência CPU e TTS provisório podem ser lentos
ou robóticos. O Hosted Profile ainda carrega capacidades que convergirão ao
Native. Voz física, química, beleza e utilidade pessoal final não foram julgadas.

Nenhum benchmark científico, RAPL, energia, PyTorch ou Inductor foi iniciado.
Nenhum Cloud, USB, block device ou QPU foi liberado.

## Errata e resselamento do launcher

A primeira abertura humana revelou que o WSH deste host rejeita o BOM UTF-8 no
início de `START_CASULO_OWNER.vbs` (`800A0408`, linha 1, caractere 1). A falha
ocorreu antes de qualquer VM, modelo, memória ou criação ser iniciada. O pacote
afetado foi preservado sem reclassificação.

O gerador passou a emitir os quatro launchers em Windows-1252 sem BOM. Todos
foram executados pelo `cscript.exe` real em modo de parse sem efeitos e
retornaram `CASULO_VBS_PARSE_PASS`. O gate
`RC13_HANDOFF_COMPLETE_VBSCRIPT_RESEAL` passou, a assinatura Ed25519 de
desenvolvimento foi verificada e o manifesto corrente é
`b6bfaa8166b0b2174392be64c1936a266e8a8cd119c9c7a8ab5e38017c2c4196`.
