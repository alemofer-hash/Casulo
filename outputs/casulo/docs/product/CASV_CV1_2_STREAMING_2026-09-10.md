# CV1.2 — container segmentado e reprodução incremental

Estado: `PASS_STREAM_CONTAINER_ENGINEERING_GATE`

## Resultado

Foi implementado e executado o CASV/0.2, um layout próprio com payloads
segmentados seguidos de manifesto hasheado no footer. O encoder escreve em
ordem crescente sem backpatch; o decoder independente reconstrói um segmento
por vez; o player valida integralmente e então envia segmentos diretamente ao
ffplay por stdin.

Isso elimina o limite de manter a mídia canônica inteira em memória no
container/decoder. Ainda falta tornar a etapa FFmpeg de importação incremental:
o comando `casv-stream-pack` recebe hoje um arquivo raw canônico já existente.

## Implementação

- `casv_stream_archive.py`: encoder forward-only, seleção T por segmento,
  manifesto/footer e selo de evidência;
- `independent_casv_stream.py`: inspect, verify, unpack e range extraction sem
  importar o caminho de encode;
- `casv_player.py`: detecção 0.1/0.2 e perfil incremental de duas passagens;
- `casv_stream_probe.py`: prova sintética curta append-only, com controle de
  corrupção;
- CLI: `casv-stream-pack`, `inspect`, `verify`, `unpack`, `extract` e `probe`.

O índice é protegido por SHA-256, mas não é assinado. O texto e os receipts não
usam “autenticado” como sinônimo indevido de assinatura.

## Prova executada

Campanha append-only:

```text
C:\CasuloLab\campaigns\2026-09-10-casv-stream-v02-probe-attempt4
```

As tentativas 1–3 permanecem preservadas. A tentativa 4 foi criada, sem
overwrite, depois de fundir o cálculo do SHA-256 à passagem de verificação e
incluir no relatório os hashes da implementação que produziu a evidência.

Corpo sintético misto RGB8, 64x36, 16 frames, 24 fps:

| Métrica | Valor |
|---|---:|
| bytes canônicos | 110.592 |
| SHA-256 canônico | `ecc52aaa43a486725c90b3a20548bf10e5a6c42d8e4a29b1a1b1da0e81086987` |
| segmentos | 27 |
| segmentos raw | 13 |
| segmentos zlib | 14 |
| bytes do `.casv` | 68.344 |
| SHA-256 do `.casv` | `b188660a185412acf7caaa1306672465d632fba53edd67da79cac24285c0c22f` |
| redução versus raw sintético | 38,201678241% |
| maior segmento canônico | 4.096 bytes |
| máximo de buffers explícitos | 8.192 bytes |

A redução é somente contra a representação raw do corpus sintético construído
para exercitar os dois modos. Não é comparação com MP4, HEVC, zstd ou 7-Zip.

## Gates observados

Todos passaram:

1. round-trip integral byte a byte;
2. SHA-256 integral idêntico;
3. extração exata de quatro frames;
4. extração seletiva sem alegar verificação do restante;
5. modo raw realmente exercido;
6. modo zlib realmente exercido;
7. uma decisão T por segmento;
8. um julgamento T pós-decode;
9. corrupção do primeiro segmento recusada;
10. ausência de bitstream MP4/HEVC.

Houve 27 decisões de armazenamento e um julgamento de custo, todos em receipts
encadeados. Identidades atuais:

```text
T source  69f36035a710f9546c85d567de86cd4285c4c30543727654f98f2754dad5335f
T IR      b76c964d0f7978436fc65709641e251777a7c47d7a8f28715c747afbb7ae84b3
TCAP      8fdcb3fb294a4563efb639327dda9e8b2dba33519211f70a15ace161108f91e0
chain     fe36d759710ceb817dff05dc54dfd0a5e2f6ecfa5fbcf07dc49c75ec4d12f0b4
```

O player real abriu o `.casv`, enviou 110.592 bytes por pipe, não reteve mídia
temporária e encerrou com `PASS`.

## Validação

```text
focused CASV                         18 passed
compression + T integrated          92 passed
ruff targeted                       PASS
CLI stream inspect                  exit 0
CLI stream verify                   exit 0
ffplay incremental                  PASS
evidence manifest                   52/52 hashes PASS
```

Selos:

```text
MANIFEST.json  3c5492d8c93b79fc51639a8ead4fa0733c547cc9d265d42127ac3a6d672dc1a0
SHA256SUMS      a94396197b166dc3ce59a68dbd9a7e65f98dd24dec34e4ef3bded447702356e5
```

## Veredito

O caminho de infraestrutura está positivo: arquivos maiores agora podem ser
gravados e reconstruídos com memória limitada por segmento, seek seletivo e
player sem raw temporário. O resultado de compressão natural continua
desconhecido. CASV/0.2 deliberadamente usa apenas raw/zlib por segmento e não
avança a hipótese principal de explicar vídeos naturais por
`base + dinâmica + residual`.

Próximo passo: ligar FFmpeg stdout diretamente ao encoder segmentado, definir
áudio canônico sincronizado e portar a representação generativa para segmentos
com uma gramática visual mais expressiva. Depois, executar clips naturais
pequenos e publicar derrotas/ganhos contra o arquivo de origem.
