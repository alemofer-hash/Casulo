# CASV/0.5 — container visual causal compacto

Estado: `IMPLEMENTED_BOUNDED_ENGINEERING_GATE`

## Finalidade e fronteira

CASV/0.5 mantém os transforms espaciais reversíveis de CASV/0.4 e substitui o
manifesto JSON embutido por um índice binário mínimo. O objetivo específico é
preservar no arquivo final a economia encontrada nos payloads, sem retirar da
conta cabeçalhos, índice, hashes ou footer.

O contrato continua sendo `EXACT_MEDIA`: a identidade protegida é o stream de
amostras canônicas declarado. O container MP4/HEVC de origem e o áudio não são
embutidos nem reconstruídos. Logo, igualdade da mídia canônica não significa
igualdade byte a byte com o arquivo MP4 original.

## Ordem canônica

| Pixel format | Ordem | Bytes por amostra/pixel |
|---|---|---:|
| `RGB8` | frame → faixa → pixel RGB | 3 |
| `YUV444P10LE` | frame → plano Y/U/V → faixa → amostra little-endian | 2 |

Geometria de registros e tiles é derivada de `width`, `height`,
`frame_count`, `pixel_format`, `tile_width` e `strip_height`. Ela não é repetida
no índice.

## Layout binário

Todos os inteiros são big-endian.

```text
magic CASV 00 05 CR LF                              8 bytes
header                                              72 bytes
  pixel_format_id                       uint8
  flags                                 uint8       deve ser 0
  header_size                           uint16      deve ser 72
  width                                 uint32
  height                                uint32
  frame_count                           uint32
  fps_numerator                         uint32
  fps_denominator                       uint32
  tile_width                             uint32
  strip_height                           uint32
  canonical_bytes                       uint64
  canonical_sha256                      32 bytes

para cada registro derivado:
  magic CVC5                              4 bytes
  record_index                          uint32
  selected_payload_bytes                uint32
  canonical_strip_sha256                 32 bytes
  para cada tile derivado:
    storage_mode_id                       uint8
    stored_length                        uint32
  payloads dos tiles, na ordem canônica

footer CV5END CR LF                                76 bytes
  magic                                   8 bytes
  selection_receipt_count               uint32
  selection_receipt_chain_head            32 bytes
  sha256 de todo conteúdo anterior         32 bytes
```

O overhead determinístico é:

```text
156 + 44 × record_count + 5 × tile_count bytes
```

Os modos são:

| ID | Modo |
|---:|---|
| 0 | `CANONICAL_RAW` |
| 1 | `CANONICAL_ZLIB` |
| 2 | `DC_XOR_ZLIB` |
| 3 | `PAETH_ZLIB` |

## Integridade e limites

O decoder independente valida, antes de aceitar:

- magic, versão, flags e tamanho do header;
- dimensões, pixel format e aritmética do total canônico;
- quantidade e ordem exatas de registros;
- geometria derivada de todas as faixas e tiles;
- limites de 100.000 registros, 65.536 tiles por registro, 8 MiB por tile e
  64 MiB por faixa;
- modo, comprimento individual e soma do payload;
- ausência de trailing bytes;
- hash de conteúdo do container;
- hash de cada faixa reconstruída;
- tamanho e SHA-256 do stream canônico integral;
- cardinalidade e head não nulo da cadeia de receipts de seleção.

Zlib é decodificado com limite explícito de saída. Um payload não pode expandir
além da geometria declarada. O decoder usa apenas a biblioteca padrão e não
importa encoder, IR, adapter de autoridade nem runtime T.

## Autoridade causal de T

`compression_casv_compact.t` recebe os quatro candidatos já reconstruídos
localmente. Para cada tile, T escolhe um modo antes de o registro ser
confirmado. Batching reduz inicializações de processo, mas cada tile usa uma
máquina semântica nova e recebe receipt e elo próprios.

Depois de o candidato completo ser fechado e reconstruído pelo decoder
independente, T recebe:

```text
exact_reconstruction
no_foreign_bitstream
source_bytes
archive_bytes
reference_zlib_bytes
partition_exact
cancelled
```

O juízo é consumido antes do `rename` atômico:

| Veredito | Condição | Efeito |
|---|---|---|
| `ACCEPT_BEATS_REFERENCE` | archive < zlib global | publica |
| `ACCEPT_RAW_ONLY` | zlib global <= archive < raw | publica como não competitivo |
| `REJECT` | archive >= raw ou precondição recusada | não publica; preserva candidato em evidência |

A policy mutante `compression_casv_compact_force_raw.t` força somente a
decisão de storage. Writer, primitives e decoder não mudam. Essa mutação é o
controle causal da autoridade T.

## Baseline de custo

O baseline interno é zlib RFC 1950/DEFLATE nível 9 aplicado, em streaming, a
toda a sequência canônica. Os timestamps reais não participam da conta. O
relatório registra versões compile/runtime da biblioteca zlib, bytes de:

- payload selecionado;
- record stream completo;
- overhead fixo;
- archive completo;
- baseline zlib completo.

O juízo econômico usa exclusivamente o archive completo. Não é permitido
chamar economia de payload de vitória do arquivo.

## Proveniência fora do bitstream

O arquivo contém metadados mínimos de reprodução e a âncora da cadeia de
seleção. TCAP, fonte T, traces, receipts detalhados, hashes de implementação e
proveniência extensa ficam no pacote de evidência externo. Isso separa dois
custos que devem ser reportados, nunca confundidos:

1. bytes necessários para armazenar e reconstruir a mídia (`archive`);
2. bytes adicionais necessários para auditar a decisão experimental
   (`authority_artifacts`).

O segundo custo não é necessário ao playback, mas é obrigatório para a prova
causal reproduzível.

## O que o formato não implementa

- predição temporal entre tiles ou frames;
- movimento, objetos, câmera, oclusão ou semântica visual aprendida;
- preditor numérico específico para 10 bits;
- áudio;
- random access por índice temporal;
- escolha T de canonicalização, crop, pixel format ou geometria;
- vantagem demonstrada contra HEVC, FFV1, x265 lossless ou zstd;
- compressão de vídeo 8K integral;
- compressão próxima de 100%.

CASV/0.5 é um formato experimental exato, não um codec de distribuição pronto.
