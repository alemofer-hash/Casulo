# CASV/0.2 — container visual segmentado

Estado: `IMPLEMENTED_STREAMING_CONTAINER_ENGINEERING_GATE`

## Finalidade e fronteira

CASV/0.2 transforma uma sequência de mídia canônica já decodificada em um
arquivo próprio, forward-only e segmentado. Ele não é ZIP, MP4 ou HEVC e não
embute o bitstream da fonte. O contrato continua sendo `EXACT_MEDIA`:

```text
SHA-256(bytes canônicos de entrada)
  == SHA-256(bytes reconstruídos pelo decoder independente)
```

O corte 0.2 resolve infraestrutura de arquivos maiores: escrita sem backpatch,
memória limitada por segmento, índice ao final, reconstrução incremental,
extração de quadros e reprodução por pipe. O adapter implementado em CV1.3
também liga FFmpeg stdout diretamente ao encoder. O formato ainda não
implementa áudio nem uma gramática generativa segmentada de vídeo natural.

## Formatos canônicos

O manifesto aceita exatamente:

| Identificador | Layout | Bytes por pixel |
|---|---|---:|
| `RGB8` | RGB packed, 8 bits por canal | 3 |
| `YUV444P10LE` | três planos Y, U e V; UInt16 LE por amostra de 10 bits | 6 |

Para `YUV444P10LE`, a identidade é relativa ao fluxo nativo decodificado pela
versão registrada do FFmpeg. Não é identidade do MP4/HEVC original nem prova
de que decoders diferentes produzam bytes idênticos.

## Layout binário

Todos os inteiros do footer são big-endian.

```text
CASV 00 02 CR LF                 8 bytes
segmento armazenado 0            N0 bytes
...
segmento armazenado k            Nk bytes
manifesto JSON canônico          M bytes
CV2IDX CR LF                     8 bytes
comprimento do manifesto         UInt64
SHA-256 do manifesto             32 bytes
```

O encoder grava nessa ordem em `<destino>.casv-part`, faz `flush` + `fsync` e
publica com substituição atômica. O header não é reescrito. O manifesto fica no
footer porque offsets e decisões T só são conhecidos após os segmentos.

O JSON é UTF-8, com chaves ordenadas e sem whitespace opcional. O decoder
rejeita representação JSON não canônica, versão futura, bytes finais, gaps,
offsets sobrepostos, hashes inválidos e qualquer declaração de bitstream
estrangeiro.

## Segmentos

Cada entrada registra:

- índice e ranges contíguos no payload e na mídia canônica;
- comprimento e SHA-256 da forma canônica;
- `CANONICAL_ZLIB` ou `CANONICAL_RAW`;
- comprimento e SHA-256 da forma armazenada;
- hash do receipt da decisão T correspondente.

Zlib é uma primitive estrangeira declarada como RFC 1950. T escolhe se ela é
usada; T não implementa o compressor. O encoder nunca armazena zlib se ele for
maior que o bloco raw, portanto `stored_length <= canonical_length` é invariante
validado pelo decoder.

O caminho generativo de `base + dinâmica + residual` do CASV/0.1 ainda não foi
segmentado no 0.2. O manifesto declara
`generative_candidate_available=false`; isso torna o 0.2 atual infraestrutura
streaming, não sucesso de compressão causal natural.

## Autoridade T

Para cada segmento, T recebe antes da gravação:

- `segment_index`;
- `canonical_sha256`;
- disponibilidade e exatidão do candidato generativo;
- ausência de bitstream estrangeiro;
- bytes de cada candidato.

Cada chamada possui ID distinto, receipt encadeado e hash referenciado pelo
segmento. Ao fim da reconstrução independente, uma chamada T separada julga
`ACCEPT` ou `REJECT` usando o custo total do archive. O archive comita a cadeia
de seleção; a evidência externa preserva também o julgamento pós-decode.

## Decoder independente e memória

`independent_casv_stream.py` não importa encoder, IR, proposer ou runtime T. O
decoder:

1. lê e valida footer e manifesto;
2. valida ranges e limites antes de alocar segmentos;
3. lê um segmento armazenado;
4. valida seu hash;
5. reconstrói com limite declarado;
6. valida hash canônico;
7. entrega o bloco e segue adiante;
8. valida tamanho e SHA-256 da mídia inteira.

O relatório expõe separadamente o maior bloco armazenado, o maior bloco
canônico e a soma máxima dos buffers explícitos. Isso não é medição de RSS do
processo; overhead de Python/zlib não foi medido.

## Seek e escopo de integridade

A extração seletiva lê o footer, o manifesto e somente os segmentos que
intersectam os quadros pedidos. Ela valida o hash do índice e os hashes desses
segmentos. Por isso retorna:

```text
SELECTED_SEGMENTS_AND_HASH_VERIFIED_INDEX
whole_archive_payload_verified=false
```

O SHA-256 do footer é detecção de integridade, não assinatura nem autenticação
contra atacante capaz de reescrever arquivo e digest. Verificação integral e
assinatura de release são contratos distintos.

## Player de referência

Para CASV/0.2, `casv-play` faz duas passagens:

1. verificação integral independente;
2. nova decodificação segmento a segmento diretamente em `ffplay pipe:0`.

Não existe arquivo temporário de mídia. O perfil reportado é
`REFERENCE_PIPE_INCREMENTAL_SEGMENTS_TWO_PASS_VERIFIED`. FFplay é apenas a
superfície de reprodução; não participa da reconstrução ou do julgamento.

## Importação direta por pipe

`casv-stream-import` congela a identidade da fonte, o probe e o tamanho
canônico antes de criar o processo. O FFmpeg escreve rawvideo em stdout; o
encoder aceita leituras curtas, mas exige exatamente o comprimento declarado e
EOF. Stderr é drenado concorrentemente com captura limitada.

O arquivo temporário do archive só é publicado depois de o produtor retornar
zero. Timeout, saída curta ou longa, falha do produtor e falha do validator
removem o `.casv-part`. A evidência parcial é preservada para diagnóstico. O
manifesto registra a versão, o hash e o comando redigido do FFmpeg, bem como
`raw_intermediate_created=false`.

Essa rota reduz uso de armazenamento temporário, mas não muda a equivalência:
a identidade continua sendo a sequência canônica decodificada, não o container
de origem.

## Limites fail-closed

- manifesto: no máximo 32 MiB;
- segmentos: de 1 a 65.536;
- bloco canônico: no máximo 64 MiB;
- dimensões: no máximo 16.384 por eixo;
- frames: no máximo 1.000.000;
- hashes: 64 caracteres hexadecimais minúsculos;
- descompressão limitada ao tamanho declarado;
- publicação de output via arquivo parcial e substituição atômica;
- destino preexistente exige `--overwrite`;
- nenhum MP4, HEVC ou outro container é aceito internamente.

## Claims autorizados e proibidos

É correto dizer que CASV/0.2 possui container próprio segmentado, escrita
forward-only, decode incremental bounded, seleção T por segmento, extração
seletiva e round-trip canônico exato exercidos em regressão sintética.

Ainda é proibido dizer que CASV/0.2 comprime vídeo natural, comprime um vídeo
8K integral, vence HEVC, alcança compressão próxima de 100%, possui áudio ou
substitui codecs maduros.
