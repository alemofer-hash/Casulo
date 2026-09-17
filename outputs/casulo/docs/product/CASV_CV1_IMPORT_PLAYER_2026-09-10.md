# CASV CV1 — importador bounded e player de referência

Estado: `PARTIAL_PASS_NATIVE_SAMPLE_AND_PIPE_STREAMING_PENDING`

## Resultado

O Casulo abriu o caminho fonte 8K -> mídia canônica -> `.casv` -> decoder
independente -> player. O arquivo CASV é próprio e não contém o MP4 nem o
bitstream HEVC. A reconstrução RGB8 foi byte a byte exata. A camada generativa
atual, porém, não venceu o fallback geral no recorte natural: T selecionou zlib
canônico porque era 802 bytes menor.

Isso valida plumbing, formato, fallback e julgamento causal. Não valida
compressão do vídeo 8K, vantagem sobre HEVC nem compressão próxima de 100%.

Depois desse primeiro probe, uma rota adicional preservou o fluxo decodificado
`YUV444P10LE` e o player passou a usar pipe, sem mídia temporária. A gramática
generativa continua restrita a RGB8; no perfil de 10 bits T seleciona somente
entre fallbacks exatos.

## Fonte e recorte executado

| Campo | Valor |
|---|---:|
| fonte | `000_10sec_8K.mp4` |
| bytes da fonte | 18.381.885.157 |
| SHA-256 da fonte | `68011a473a3c3f963dfe716620991eb92d87473e9a7204ae323a1dceb0502d24` |
| codec | HEVC |
| raster | 8192x4320 |
| formato nativo | `yuv444p10le` |
| frame rate | 60000/1001 |
| derivação | crop 0,0,256,144; 2 frames |
| mídia canônica | RGB8, 221.184 bytes |
| SHA-256 canônico | `ac2ffd7f7b16116e354e87f74abfd9ac635c600bab064c4d6feccf0fb380d2d7` |

O hash da fonte inteira foi recalculado em streaming antes do decode. Somente o
recorte foi decodificado e mantido em memória. Nenhuma compressão integral da
fonte foi iniciada.

## Contabilidade

| Candidato | Payload |
|---|---:|
| `CANONICAL_RAW` | 221.184 bytes |
| `CANONICAL_ZLIB` | 64.852 bytes |
| `GENERATIVE_EXACT` | 65.654 bytes |
| archive `.casv` selecionado | 68.031 bytes |
| archive + evidência de autoridade | 99.840 bytes |

A proposta determinística encontrou 21 tracks, mas reconstruiu exatamente
somente 3.379 de 73.728 pixels, cerca de 4,58%. O residual dominou. Isso explica
causalmente por que a descrição generativa perdeu para zlib no conteúdo
natural.

O archive reduziu 69,24% contra RGB8 cru. Esse número é apenas uma regressão de
engenharia: não há denominador isolado correspondente ao recorte dentro do
HEVC, e o MP4 já está comprimido. Portanto, não existe neste gate uma razão
CASV/HEVC defensável.

## Fronteira de equivalência

O decoder independente confirmou:

```text
SHA-256(RGB8 importado) == SHA-256(RGB8 reconstruído)
```

Mas a fonte usa 10 bits e o adaptador converte para RGB8. Logo:

- `EXACT_AFTER_RGB8_CANONICALIZATION`: comprovado;
- identidade do contêiner MP4: não prometida;
- identidade dos samples nativos `yuv444p10le`: não comprovada;
- equivalência audiovisual integral: não comprovada;
- áudio: ausente do formato 0.1.

## Preservação nativa de 10 bits

O probe corrigido e append-only `attempt2` usou a mesma fonte e o mesmo crop,
mas pediu preservação do pixel format declarado:

| Campo | Valor |
|---|---:|
| formato canônico | `YUV444P10LE` |
| bytes canônicos | 442.368 |
| SHA-256 canônico | `eb1c094a58e0c79aa7a75075c31638cd20b884a7526b0786bf16342730bc3aa8` |
| `CANONICAL_ZLIB` | 94.890 bytes |
| `CANONICAL_RAW` | 442.368 bytes |
| `GENERATIVE_EXACT` | indisponível |
| archive `.casv` | 98.485 bytes |
| archive + evidência | 134.872 bytes |
| redução contra raw canônico | 77,736861617% |

O decoder independente reconstruiu os 442.368 bytes e o mesmo SHA-256. A
política T recebeu `generative_candidate_available=false` e escolheu
`CANONICAL_ZLIB`; não foi atribuído ganho à gramática RGB8. Esse resultado
preserva o fluxo nativo decodificado pela versão hasheada do FFmpeg. Não prova
identidade do MP4, equivalência entre decoders diferentes ou vantagem sobre
HEVC.

## Player

`casv-play` foi executado sobre CASV RGB8 e `YUV444P10LE`. O player valida e
reconstrói o archive com o decoder stdlib-only e envia os bytes ao ffplay por
stdin. O processo usa uma lista de argumentos, `shell=False` e não cria mídia
temporária.

Perfil honesto: `REFERENCE_PIPE_BOUNDED_MEMORY_NOT_INCREMENTAL_DECODE`. Ainda
faltam decode incremental, backpressure, seek, checkpoints e áudio.

## Autoridade T

T/2 atravessou fonte, AST, semântica, IR, grafo, TCAP e runtime Rust. Antes do
commit do archive, decidiu entre os três candidatos e escolheu
`CANONICAL_ZLIB`. Depois da reconstrução independente, julgou o custo total.

T ainda não governa:

- proposição da cena;
- tracking;
- inferência de materiais;
- implementação do renderer.

## Evidência

Diretório append-only:

```text
C:\CasuloLab\campaigns\2026-09-10-casv-8k-import-plumbing-attempt1
```

Hashes principais:

- `.casv`: `40c91d35d58852c0930db4f98d69dc517277407dcc39e0e87c1626910bd9b604`;
- `MANIFEST.json`: `a36fb48a69b559a84ba991cdfd58fb271c3471af3499725473e26ee789968ab9`;
- `SHA256SUMS`: `261d58664483dbd7eaae3a83de24a865fc65da5debc27776511c99718e0225df`;
- `pack-report.json`: `b0a48659a2713a9b76d53a2f58752048af22da9069dcd800061a2c2501669531`.

O manifesto contém 21 entradas e foi revalidado contra os bytes preservados.

Evidência primária de 10 bits, após correção do rótulo de provenance:

```text
C:\CasuloLab\campaigns\2026-09-10-casv-8k-native10-import-attempt2
```

- `.casv`: `63b7b8bba37084f871c693ae9cc3d965cb53eaf60b616f244b4145ee8b27c5bf`;
- `MANIFEST.json`: `f9688c85386db7c7a07ad9253a9dfffc60914995a289780d72bdace182ef631c`;
- `SHA256SUMS`: `aed895cdb849aa8cd622e76e51d958dd882fe48c3dea0f43eddd214f61d49e23`;
- `pack-report.json`: `f405e01de94c2894e221453328e2171ec39a27aa24dabc35694fa5306c0a09c9`.

O manifesto corrigido também contém 21 entradas e foi revalidado. O `attempt1`
de 10 bits foi preservado, mas não é a evidência final porque rotulava o
adaptador incorretamente como RGB8.

## Próximo gate

CV1 só estará completo quando houver:

1. importação e encode segmentados com working set independente da duração;
2. decode incremental por segmento;
3. índice/checkpoints autenticados para seek;
4. áudio canônico e sincronização;
5. corrupção, cancelamento e retomada testados em todos esses caminhos;
6. renderer generativo capaz de operar sobre a precisão canônica escolhida.
