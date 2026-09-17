# ARC-10 — convergência do plano de controle Hosted/Native

Data: 2026-08-18  
Estado: `NATIVE_CONTROL_PLANE_IMPLEMENTED_AND_BOOT_VERIFIED`

## Resultado

Hosted e Native agora compartilham um contrato de UX versionado e selado:

- schema: `casulo.hosted-native-ux-contract/1.0`;
- wire: `casulo.owner-ux-event/1.0`;
- SHA-256:
  `4d209cce708d843ffef50ac606ba199151be39eb9ecfff9c2c9fae233d24bcb9`;
- 14 tipos de evento;
- prioridade `PRESENCE > FLOW > SYSTEM > BACKGROUND > AUDIT`;
- limite de evento: 32 KiB;
- fila Native: 16 eventos, fail-closed ao exceder capacidade.

O kernel possui um validador bounded sem alocação dinâmica para lifecycle do
modelo, stream do assistente e jobs. Tokens fora de ordem, job sem SHA-256,
evento duplicado e conclusão depois de cancelamento são recusados. A fila
Native seleciona presença antes de trabalho background sem mudar a política G4
histórica.

## Prova em boot

A imagem foi reconstruída offline com lock preservado e executada em QEMU/OVMF:

- imagem:
  `product-demos/human-proof/arc-native-convergence-2026-08-18-attempt1/casulo-native-arc10.img`;
- SHA-256 da imagem:
  `a0ed1c5f3229a7a23e7dfce99e8d6a0f865bd23b70014db4afc02277c20f895f`;
- SHA-256 do manifest:
  `e9e98c6c3027df24fdc607b51125a2ddb4d0aaaa68413a6ab27bc5ac74731033`;
- produto Python: `517 passed, 1 skipped`;
- Cargo check locked/offline: PASS;
- QEMU: TCG, 2 vCPUs, rede desligada, imagem read-only, nenhum block device do
  host e nenhuma escrita física;
- benchmark científico, desempenho e energia: não medidos.

O serial real registrou `PASS` para presença prioritária, lifecycle do modelo,
stream do assistente, lifecycle de jobs, rejeição de conclusão tardia, fila
bounded e gate integrado.

## Fronteira honesta

ARC-10 porta o plano de controle, não os adapters pesados. Continuam Hosted:

- Qwen/llama.cpp e inferência neural;
- captura/reprodução de áudio físicos;
- Living Memory protegida por DPAPI;
- Creation Field renderer;
- materializador e execução externa.

Native já fornece timer, serial, framebuffer, ramdisk, isolamento TCAP e o novo
event loop de produto. Portanto, a experiência ARC-9 pode manter um único
contrato enquanto drivers migram gradualmente, mas ainda não existe experiência
voice-first completa inteiramente dentro do kernel.

## Próximo gate

ARC-11 pertence a Guilherme: bootar a experiência owner, conversar, criar algo
inédito, corrigir, materializar, reiniciar e retomar. Automação não pode aprovar
química, voz, prazer de uso ou ausência de fricções humanas P0/P1 em nome dele.

