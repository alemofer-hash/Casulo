# CV1.3 — FFmpeg direto para CASV/0.2

Estado: `PASS_DIRECT_PIPE_ENGINEERING_GATE_AUDIO_CONTRACT_ONLY`

## Resultado

O adaptador agora envia `FFmpeg stdout` diretamente ao encoder segmentado
CASV/0.2. Não existe arquivo raw intermediário. O produtor, o encoder e o
decoder usam backpressure natural do pipe e memória limitada pelo segmento.

A publicação continua fail-closed: o encoder só faz o rename atômico depois de
receber exatamente o número declarado de bytes, confirmar EOF e observar que o
FFmpeg terminou com exit code zero. Saída curta, byte excedente, timeout,
stderr não drenado ou exit code não zero deixam apenas evidência parcial e
nunca publicam o `.casv`.

O contrato canônico de áudio foi implementado e testado separadamente. Áudio
**não** foi integrado ao CASV/0.2; `audio_included=false` continua verdadeiro.

## Probe real delimitado

Fonte imutável:

```text
C:\CasuloLab\incoming\000_10sec_8K.mp4
18.381.885.157 bytes
SHA-256 68011a473a3c3f963dfe716620991eb92d87473e9a7204ae323a1dceb0502d24
HEVC, 8192x4320, yuv444p10le, 60000/1001 fps
```

Derivação predefinida: crop `256x144 @ 0,0`, dois quadros, preservando o fluxo
decodificado `YUV444P10LE`. O hash da fonte inteira foi validado antes de abrir
o pipe.

| Métrica | Valor |
|---|---:|
| bytes canônicos | 442.368 |
| SHA-256 canônico | `eb1c094a58e0c79aa7a75075c31638cd20b884a7526b0786bf16342730bc3aa8` |
| segmentos | 7 |
| segmentos zlib | 7 |
| segmento alvo | 65.536 bytes |
| bytes de payload persistido | 95.539 |
| overhead do container | 7.214 bytes |
| bytes do `.casv` | 102.753 |
| SHA-256 do `.casv` | `e7497d3aa0c58b9f19e938997c001991f9031be8581348c95fc93e3a717c332f` |
| redução versus raw canônico | 76,772054036% |
| artifacts externos de autoridade | 49.560 bytes |
| `.casv` + autoridade | 152.313 bytes |
| redução versus raw incluindo autoridade | 65,568712023% |
| tempo monotônico do processo FFmpeg/pipe | 21,3251675 s |

O SHA-256 canônico coincide com a rota bounded anterior para a mesma fonte,
crop, quadros, pixel format e toolchain. Isso é uma verificação cruzada da
derivação decodificada; não é identidade do MP4/HEVC.

O diretório final contém zero arquivo `.raw`. O decoder independente verificou
todos os segmentos e o player enviou 442.368 bytes diretamente ao ffplay, com
exit code zero.

## Autoridade e proveniência

T tomou sete decisões de armazenamento antes do commit e emitiu um julgamento
de custo após a reconstrução independente. Todos os segmentos escolheram
`CANONICAL_ZLIB`; o candidato generativo continua indisponível para 10 bits.

```text
T source  69f36035a710f9546c85d567de86cd4285c4c30543727654f98f2754dad5335f
T IR      b76c964d0f7978436fc65709641e251777a7c47d7a8f28715c747afbb7ae84b3
TCAP      8fdcb3fb294a4563efb639327dda9e8b2dba33519211f70a15ace161108f91e0
```

O manifesto registra versões e hashes de FFmpeg/ffprobe, argumentos com o
caminho da fonte redigido, hashes das implementações, timestamps UTC,
cronômetro monotônico, stderr bounded e ausência do bitstream estrangeiro.

## Validação

```text
novo adapter/pipe                     8 passed
contrato de áudio                    14 passed
compressão focal                     59 passed
compressão + áudio + pipeline T      163 passed, 42 subtests passed
ruff focal                            PASS
compileall                            PASS
CLI inspect/verify                    exit 0
ffplay incremental real              PASS
manifesto de evidência                27/27 hashes PASS
```

Selos da campanha:

```text
archive       e7497d3aa0c58b9f19e938997c001991f9031be8581348c95fc93e3a717c332f
MANIFEST.json 083360ce7dd3013d8ca35e70a35bf59fc1e1573b5e53283943b243e6d775c563
SHA256SUMS    781e1b84db9c2faf776e5ba94761bad0dc21265b3532d51ebf5e33960bb3f9f2
```

Evidência append-only:

```text
C:\CasuloLab\campaigns\2026-09-10-casv-8k-direct-pipe-attempt1
```

## Leitura honesta

O resultado fecha um gargalo de infraestrutura: a mídia decodificada não
precisa mais existir inteira em RAM ou em disco antes do encode CASV. Ele não
prova vantagem contra HEVC, porque somente dois quadros de um crop foram
processados e a razão publicada é contra amostras raw. O `.casv` atual usa zlib
e é maior que o archive bounded anterior devido ao índice segmentado e sua
proveniência; isso é custo real, não regressão escondida.

Não foram executados vídeo integral, compressão natural generativa, áudio,
Cloud, USB ou benchmark energético.

Próximo gate: integrar a gramática `base + dinâmica + residual` ao modelo de
segmentos, acrescentar representação visual nativa de 10 bits e executar clips
naturais pequenos contra o arquivo recebido e codecs maduros. A trilha de
áudio avança somente em uma nova versão audiovisual do formato.
