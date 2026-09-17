# CASV/0.3 — programas causais segmentados

Estado: `IMPLEMENTED_SHORT_ENGINEERING_GATE`

## Finalidade

CASV/0.3 é a primeira versão segmentada que executa a representação:

```text
mídia canônica = render(base, dinâmica) XOR residual exato
```

O encoder constrói, para cada grupo de quadros, três candidatos reais:

1. `GENERATIVE_EXACT`: base visual, dinâmica linear e residual XOR;
2. `CANONICAL_ZLIB`: bytes canônicos comprimidos como RFC 1950;
3. `CANONICAL_RAW`: bytes canônicos sem transformação.

A política compilada em T recebe a disponibilidade, a prova de fechamento
exato e o custo de cada candidato. Sua decisão é consumida antes de o segmento
ser gravado. O decoder independente reconstrói o candidato selecionado sem
importar encoder, proposer, IR ou runtime T.

O formato não contém MP4, HEVC ou outro bitstream estrangeiro. A equivalência é
com a sequência canônica decodificada declarada, não com os bytes do container
de origem.

## Formatos canônicos

| Identificador | Layout | Bytes por pixel |
|---|---|---:|
| `RGB8` | pixels RGB packed, 8 bits por canal | 3 |
| `YUV444P10LE` | três planos Y, U e V; cada amostra em UInt16 little-endian com 10 bits válidos | 6 |

O renderer 0.3 implementa os dois layouts nativamente. Não há conversão para
RGB8 no caminho `YUV444P10LE`.

## Segmentação atual

Um segmento contém um número inteiro de quadros completos. Os ranges de frames
e bytes são contíguos e redundantes de propósito: o decoder verifica que:

```text
canonical_offset = frame_start * frame_bytes
canonical_length = frame_count * frame_bytes
```

O limite canônico de um segmento é 64 MiB. Um quadro 8192×4320
`YUV444P10LE` possui 212.336.640 bytes e, portanto, **não cabe** nesse desenho.
CASV/0.3 recusa esse caso antes de ler o stream e declara que spatial tiling é
necessário. Essa recusa é uma limitação real, não um erro contornado.

## Layout do archive

```text
CASV 00 03 CR LF                         8 bytes
segmento selecionado 0                  N0 bytes
...
segmento selecionado k                  Nk bytes
manifesto JSON canônico                 M bytes
CV3IDX CR LF                             8 bytes
comprimento do manifesto                UInt64 big-endian
SHA-256 do manifesto                    32 bytes
```

O archive é escrito em uma única direção em `<destino>.casv-part`. O rename
atômico só ocorre depois de tamanho exato, EOF e eventual validator do produtor.

## Programa de segmento

### Envelope `CVG3`

```text
magic                      4 bytes
base_length                UInt32 BE
dynamics_length            UInt32 BE
residual_mode              UInt32 BE
residual_length            UInt32 BE
base                       base_length bytes
dynamics                   dynamics_length bytes
residual                   residual_length bytes
```

`residual_mode=0` significa residual inteiramente zero e payload vazio.
`residual_mode=1` significa residual XOR comprimido por zlib. Em ambos os
casos, o comprimento lógico do residual é exatamente o comprimento canônico.

### Base `CVB3`

A base declara formato, dimensões, quantidade de quadros, frame rate, materiais,
background e retângulos. Cada material possui três canais `UInt16 BE`. Os
valores devem caber em 0–255 para RGB8 ou 0–1023 para YUV10.

Cada retângulo declara posição inicial, largura, altura, material e z-index.
Z-index é único. A geometria precisa permanecer dentro do frame em todos os
quadros do segmento.

### Dinâmica `CVD3`

Para cada retângulo, a dinâmica armazena `dx` e `dy` inteiros por quadro. O
renderer atual é propositalmente mínimo: background uniforme, retângulos
pixel-aligned e movimento linear. Não há alpha, gradiente, textura, câmera,
oclusão, deformação nem iluminação espacial.

## Proposer e residual

O proposer atual:

1. obtém o material mais frequente do primeiro quadro como background;
2. examina até 64 materiais adicionais;
3. aceita apenas materiais que formem um retângulo cheio em todos os quadros;
4. exige translação linear inteira;
5. limita o programa a 32 tracks;
6. renderiza a hipótese;
7. calcula XOR byte a byte contra a entrada;
8. comprime o residual ou usa residual zero.

A proposta é limitada a 1.000.000 de pixels por segmento. A implementação
atual pode percorrer todos os pixels para cada material candidato, portanto seu
pior caso é aproximadamente `O(candidatos × frames × pixels)`. Isso é uma
dívida de desempenho explícita.

O residual não é erro tolerado: ele contém toda divergência entre previsão e
entrada. A reconstrução só passa quando tamanho e SHA-256 coincidem.

## Autoridade T

Por segmento, T recebe:

- índice e SHA-256 canônico;
- disponibilidade do programa;
- fechamento exato do programa;
- ausência de bitstream estrangeiro;
- bytes de programa, zlib e raw.

A política padrão escolhe o menor payload exato. Uma política de mutação
`compression_casv_force_raw.t` altera somente T e força raw. O encoder e as
primitives permanecem iguais; TCAP, receipts e storage mode mudam, enquanto o
SHA-256 reconstruído permanece igual.

T governa seleção e julgamento de custo. T ainda não governa scene proposal,
tracking, inferência de materiais ou implementação do renderer. Esses pontos
são reportados em `not_yet_governed_by_t`.

## Manifesto por segmento

Cada entrada inclui:

- ranges de frame, bytes canônicos e bytes armazenados;
- SHA-256 canônico e armazenado;
- custos dos três candidatos, usando `null` quando programa indisponível;
- modo selecionado;
- metadados da proposta causal;
- hash do receipt T que autorizou o commit.

Metadados causais incluem bytes de base/dinâmica/residual, materializador,
tracks, pixels previstos exatamente e bytes não zero do residual.

## Decoder independente

`independent_casv_program_stream.py` replica somente a especificação binária.
Ele:

1. valida magic, footer, JSON canônico e limites;
2. valida ranges contíguos de frame, mídia e payload;
3. valida custo e hash do candidato selecionado;
4. interpreta `CVG3`, `CVB3` e `CVD3` quando necessário;
5. renderiza RGB8 ou YUV10 planar;
6. descomprime residual com limite explícito;
7. fecha XOR;
8. valida SHA-256 por segmento e integral;
9. publica reconstrução por rename atômico.

A extração seletiva lê somente segmentos intersectados e declara
`whole_archive_payload_verified=false`. O player verifica o archive inteiro na
primeira passagem e o renderiza incrementalmente para `ffplay pipe:0` na
segunda.

## Adapter FFmpeg

`casv-program-import` reutiliza o plano congelado do adapter 0.2. FFmpeg envia
rawvideo diretamente por stdout. Não existe raw intermediário. Saída curta,
longa, timeout ou exit code não zero impedem publicação.

FFmpeg é uma primitive estrangeira manifestada. CASV não a apresenta como
parte first-party do codec.

## Áudio

`audio_included=false` é invariante do 0.3. O contrato PCM separado não está
integrado ao container. Uma versão audiovisual futura deverá definir timeline,
seek, sincronização e fechamento exato sem reclassificar 0.3.

## Claims

É correto afirmar que CASV/0.3 executou programas segmentados
`base + dinâmica + residual`, renderer nativo RGB8/YUV444P10LE, decisão causal
T e reconstrução independente exata em probes curtos.

Ainda não é correto afirmar que o formato:

- comprime vídeo 8K integral;
- vence HEVC, FFV1, AV1, zstd ou outro codec maduro;
- generaliza o ganho observado para vídeos naturais;
- alcança compressão próxima de 100%;
- possui áudio;
- possui spatial tiling ou memória bounded para um quadro 8K;
- é um produto comercial final.
