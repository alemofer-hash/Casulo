# Estado de execução — janela Native 24h

Campanha: `2026-08-22-native-24h`  
Estado: `CASULO_NATIVE_BOOT_TO_CREATION_PROOF`  
Objetivo técnico: concluído  
Prova humana: não executada em nome de Guilherme

## Gates concluídos

- H0: baseline, worktree e fronteiras preservados;
- NP7: 36 blocos, KV bounded, logits e contabilidade integral;
- NP8: primeiro token derivado do modelo, confrontado com oráculo;
- NP9: streaming/cancelamento exercidos; defeito RoPE mult-token descoberto e
  preservado na errata;
- NP10: RoPE NeoX corrigido, 34 tokens idênticos ao oráculo, política T causal,
  CreationSpec, compilação, execução, simulação, aceitação e materialização;
- prova positiva: 3/3 boots PASS;
- prova negativa: 1/1 cancelamento fail-closed PASS;
- Cargo/Native workspace: PASS;
- regressão Python de produto/T/QEMU: PASS;
- public audit: sem componentes owner privados;
- Cloud `RELEASE_LOCKED`, rede guest OFF, USB/block devices não tocados.

## Identidades congeladas

- imagem: `release/casulo-native-neural-port-np10-attempt-5.img`, SHA-256
  `25193857a96d6c14328d92fb128d6e666a31478dee05cc8cca6a35252932a534`;
- modelo owner: 2.497.280.256 bytes, SHA-256
  `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5`;
- system pack: SHA-256
  `4f5e9fb34de09a3fe59b49c233802312a1c2e4d86ec7d00ca2d1dc1638f7eeb1`;
- saída neural:
  `NOME=SomeDoisNumeros;FUNCAO=SomeDoisNumeros;ENTRADA=numero1,numero2;SAIDA=resultado.`;
- resultado executado: `18`;
- fonte T gerada e compilada: SHA-256
  `cc120e8f626c222674f8d950027f2265a05a59bd2167689bc746273f557ea0b3`.

## Evidência autoritativa

- `docs/product/NATIVE_BOOT_TO_CREATION_PROOF.md`;
- `docs/product/NP9_DECODER_FIDELITY_ERRATA.md`;
- `outputs/casulo/native-boot-to-creation/2026-08-22-np10-attempt-11/normal-three-final.json`;
- `outputs/casulo/native-boot-to-creation/2026-08-22-np10-attempt-12/cancel-final.json`;
- selo final:
  `outputs/casulo/native-boot-to-creation/2026-08-22-np10-final-attempt-4/seal.json`,
  SHA-256
  `fe4a98ca3b0c9eb7f2a849528b0cfca62c7839efdbf2c8ae94bf6bca46e272b7`;
- pacote reproduzível final:
  `release/CASULO_NATIVE_BOOT_TO_CREATION_PROOF_2026-08-22-attempt-4.zip`,
  364.930 bytes, SHA-256
  `368433243159ce28c4e54b39774792bdae39d8748d3b24786fb5dbd60dde863e`;
- manifest final: SHA-256
  `4fb09152ce67dba8fe05dba830351e628b74b44478fa97df3c44c34d7621560c`;
- assinatura Ed25519 de desenvolvimento: PASS; o GGUF não foi redistribuído.
- auditoria e handoff pós-selo:
  `outputs/casulo/native-boot-to-creation/2026-08-22-np10-final-attempt-4/`,
  com `POST_SEAL_SHA256SUMS` SHA-256
  `69ccf755e6e86bd8f99ec67dca45b2035cd9889c4e63d52a6f68afc068aec02e`;
- reprodução independente do selador: `attempt-5.zip` possui exatamente os
  mesmos 364.930 bytes e o mesmo SHA-256 do `attempt-4.zip`;
- espaço livre ao encerramento: 69.863.391.232 bytes (`65,07 GiB`).

A primeira tentativa de selo falhou no verificador textual de assinatura no
Windows e permanece marcada inválida. A tentativa 2 foi assinada, mas seu layout
plano dependia da árvore original e está superseded. A tentativa 3 corrigiu o
layout, mas ainda carregava timestamp variável no SBOM. A tentativa 4 é a
autoritativa; a tentativa 5 é sua reprodução bit a bit.

## Regressão final

- produto/T/QEMU: `593 passed, 2 skipped`;
- foco do launcher, pack e proof: `10 passed`;
- `casulo-native-model` host: `19 passed`;
- `casulo-presentation-core` host: `9 passed`;
- build/check da imagem e kernel bare-metal: PASS;
- auditoria independente do ZIP extraído, manifest, `SHA256SUMS`, assinatura e
  launcher: PASS;
- auditoria public: 14 arquivos, zero componente privado.

A invocação genérica `cargo --workspace` foi preservada como inválida porque
força dependências host `std` para `x86_64-unknown-none`. Os gates separados com
targets explícitos passaram; o erro não foi ocultado nem chamado de regressão.

## Limites honestos

Este resultado prova o vertical slice congelado no kernel Casulo em QEMU/WHPX.
Não prova conversa arbitrária, velocidade de produto, GPU/TPU, drivers físicos,
memória FROZEN/WARM/HOT dos pesos, energia, compressão, superioridade ou release
comercial. Os tempos de boot observados são de minutos e continuam inadequados
para a experiência final.

## Próximo passo exato

Guilherme pode executar o launcher de inspeção em `release/` ou extrair o ZIP e
abrir `release/START_CASULO_NATIVE_CREATION_PROOF.vbs`. A próxima engenharia deve
substituir a prova congelada por um loop conversacional bounded e aplicar
working-set/prefetch de verdade antes de qualquer alegação de miniaturização. A
escrita em USB continua separadamente bloqueada até autorização literal do
dispositivo exato.
