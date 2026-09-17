# Perfil da primeira VM generativa

## Extensao Semantic Multiverse

O launcher `release/CASULO_SEMANTIC_MULTIVERSE_VM_INSPECT.ps1` referencia
diretamente a base G10 read-only e cria somente um overlay esparso; nao duplica
imagem-base nem pesos. O overlay inicial selado possui snapshot
`clean-semantic-multiverse`. O catalogo e a memoria confirmada sao retomados no
reboot, enquanto o estado HOT sempre reabre vazio. Cloud, rede do guest, USB,
shared folder, clipboard e block devices continuam negados.

- Estado: `READY_FOR_GUILHERME_SEMANTIC_MULTIVERSE_REINSPECTION`
- Snapshot de reinspecao: `clean-semantic-multiverse-reinspection`
- Estado inicial de reinspecao: `release/semantic-multiverse/initial-owner-state-reinspection-2026-08-13`
- Estado humano novo: `outputs/casulo/semantic-multiverse-vm/guilherme-reinspection-2026-08-13`
- Manifesto atual SHA-256: `31764546c2dff61f68d2b00bbe4f78060cef4d1523234e7ad59ab1c24d9ad724`
- Host: Windows 11 bare metal
- Controller: `CasuloVMController`
- QEMU: 11.0.50
- Aceleração: WHPX preferida; TCG é fallback declarado
- Máquina/firmware: Q35 + OVMF/EDK2
- Base: `release/casulo-native-generative-interactive.img`, arquivo regular e imutável
- Estado owner: overlay QCOW2 esparso, criado no primeiro start
- Snapshot inicial: criado automaticamente pelo launcher
- QMP/bridge: loopback local, capability-scoped, argv sem shell
- Rede do guest: ausente
- Clipboard/shared folder: ausentes
- Dispositivo físico: proibido
- Inferência: modelo first-party local no host, não dentro do guest
- Interface atual: texto pt-BR com streaming e cancelamento
- Áudio Native: ainda não bridged
- Renderer: `HOSTED_VM_PROFILE_FIRST_PARTY_DISPLAY`
- Design: `PROVISIONAL_OWNER_REVIEW_REQUIRED`
- Cenário integrado: G10 16/16, tentativa 12
- Evidência SHA-256: `c698f3d649f0216b173270ca33f78617c4d8c37575a410798022243a90b9c9d6`

O controller rejeita paths de dispositivo Windows, symlinks e targets fora da
raiz autorizada. A base não é gravada; crash, restore e reset afetam somente o
overlay. O bridge não é um túnel genérico e não oferece rede ao guest.

Limitações honestas: o guest é reiniciado por volta de conversa no launcher
atual; a inferência ocorre no host; voz duplex e tela Native residente ainda não
integram o handoff. Esses pontos não impedem a inspeção generativa, mas impedem
alegar que o perfil Native final está completo.

Após `:criar`, o launcher projeta os 12 estados em HTML local a partir dos
receipts reais do Forge e abre um índice navegável. A projeção não inicia job,
não cria grant e permanece explicitamente provisória.
