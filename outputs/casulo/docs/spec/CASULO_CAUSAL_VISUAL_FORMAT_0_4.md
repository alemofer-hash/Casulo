# CASV/0.4 — stream visual espacialmente ladrilhado

Estado: `IMPLEMENTED_SHORT_ENGINEERING_GATE`

## Finalidade

CASV/0.4 remove a restrição estrutural do CASV/0.3 que exigia um quadro inteiro
em memória. A mídia canônica é percorrida em ordem, dividida em faixas e tiles,
e cada tile é armazenado por uma transformação reversível escolhida causalmente
por uma política T compilada.

O contrato continua sendo `EXACT_MEDIA`: a identidade exigida é a sequência de
amostras canônicas declarada, não o container MP4/HEVC recebido. O formato não
embute o bitstream de origem.

## Ordem canônica

| Pixel format | Ordem do stream | Unidade física |
|---|---|---:|
| `RGB8` | quadro → faixa horizontal de largura integral → pixels RGB | 3 bytes por pixel |
| `YUV444P10LE` | quadro → plano Y/U/V → faixa horizontal de largura integral → amostras | 2 bytes por amostra |

O layout padrão usa tiles de 512 pixels de largura e faixas de 128 linhas. A
última faixa e o último tile podem ser menores. Não há padding canônico.

Limites do formato:

- tile canônico: no máximo 8 MiB;
- faixa canônica: no máximo 64 MiB;
- tiles por faixa: no máximo 65.536;
- registros: no máximo 100.000;
- manifesto: no máximo 64 MiB.

Para um quadro 8192×4320 `YUV444P10LE`, a aritmética de layout produz 102
faixas e 1.632 tiles. A maior faixa tem 2.097.152 bytes e o maior tile 131.072
bytes. Esse cálculo foi exercido sem alocar o quadro de 212.336.640 bytes. Não
é evidência de encode 8K integral.

## Candidatos reversíveis

O encoder constrói e fecha localmente quatro candidatos antes de consultar T:

1. `DC_XOR_ZLIB`: amostra modal do tile, XOR e zlib RFC 1950;
2. `PAETH_ZLIB`: predição Paeth byte a byte e zlib RFC 1950;
3. `CANONICAL_ZLIB`: zlib dos bytes canônicos do tile;
4. `CANONICAL_RAW`: bytes canônicos sem compressão.

No caminho de 10 bits, Paeth opera sobre a representação bytewise little-endian.
Isso é reversível, mas não é ainda um preditor numérico especializado nos dez
bits válidos.

O custo entregue a T inclui a entrada binária de 16 bytes do tile e o payload.
Cabeçalhos de faixa, manifesto e footer não entram na seleção local do tile. O
juiz final atual compara o archive completo somente ao raw canônico; por isso
`ACCEPT` significa `archive_bytes < raw_canonical_bytes`, não vantagem contra
zlib, HEVC ou qualquer codec externo.

## Layout binário

```text
CASV 00 04 CR LF                         8 bytes
registro CVT4 0                          N0 bytes
...
registro CVT4 k                          Nk bytes
manifesto JSON canônico                 M bytes
CV4IDX CR LF                             8 bytes
comprimento do manifesto                UInt64 big-endian
SHA-256 do manifesto                    32 bytes
```

Cada registro `CVT4` contém um cabeçalho fixo de 76 bytes:

```text
magic, record_index, frame_index, plane_index,
y, width, height, bytes_per_pixel, tile_count,
canonical_length, payload_length, canonical_sha256
```

Depois vêm `tile_count` entradas de 16 bytes:

```text
x: UInt16
width: UInt16
mode: UInt8
reserved: 3 bytes
canonical_length: UInt32
stored_length: UInt32
```

Os payloads dos tiles aparecem imediatamente depois da tabela, na mesma ordem.
Offsets são derivados e também validados contra o índice do manifesto.

## Escrita e publicação

O writer publica em duas fases:

1. escreve magic, registros, manifesto e footer em `<destino>.casv-part`;
2. faz flush e `fsync`;
3. somente então executa rename atômico para o destino final.

Stream curto, stream longo, falha do validator do produtor ou arquivo parcial
impedem o rename. O temporário é removido; o diretório de evidência pode
permanecer como tentativa rejeitada.

## Autoridade causal T

A policy `examples/t-v2/compression_casv_tile.t` atravessa frontend T/2, AST,
semântica, IR, grafo, TCAP e runtime Rust. Para cada tile, recebe os quatro
custos medidos e as invariantes de fechamento. Sua resposta é consumida antes
do registro ser gravado.

O runtime suporta batch físico: todas as decisões de uma faixa usam uma única
invocação de processo Rust, mas cada item executa uma máquina T nova, tem
`call_id`, input hash, output hash, receipt e elo próprio na hash chain. O batch
amortiza startup; não transforma várias decisões em uma decisão simulada.

A mutação `compression_casv_tile_force_raw.t` muda somente a policy e força
`CANONICAL_RAW`. TCAP, receipts e bytes persistidos mudam; a mídia canônica
reconstruída permanece idêntica.

T governa nesta versão:

- escolha do modo de armazenamento de cada tile;
- julgamento final contra o raw canônico.

T ainda não governa:

- canonicalização FFmpeg;
- pixel format, crop, geometria de faixa ou tile;
- implementação de zlib e dos preditores;
- modelo temporal;
- áudio;
- política global que minimize o custo do archive completo.

## Decoder independente

`independent_casv_tiled_stream.py` usa somente a biblioteca padrão. Ele não
importa writer, IR, proposer, runtime T ou FFmpeg. O decoder:

1. valida magic, footer, hash e JSON canônico;
2. valida mídia, limites, cardinalidade e ordem de registros;
3. rejeita gaps, sobreposições e bytes extras;
4. valida hash de cada registro e sua tabela de tiles;
5. descomprime com limite explícito;
6. inverte Paeth ou DC/XOR;
7. remonta uma faixa de cada vez;
8. valida SHA-256 por faixa e da mídia integral;
9. publica unpack por rename atômico.

O working set de decode é limitado por uma faixa. O player usa esse iterador e
envia a mídia canônica por pipe ao ffplay.

## Contabilidade de tamanho

Relatórios novos separam quatro grandezas:

- `selected_tile_payload_bytes`: somente os payloads escolhidos;
- `selected_record_stream_bytes`: cabeçalhos, tabelas e payloads;
- `archive_bytes`: magic, record stream, manifesto e footer;
- `authority_artifact_bytes`: evidência externa, nunca escondida no custo
  auditável.

O campo histórico `payload_advantage_bytes_vs_direct_zlib`, presente em probes
selados anteriores à correção de nomenclatura, significava na realidade
vantagem do **record stream**. Ele foi substituído sem reescrever a evidência.

## Limitações e claims

É correto afirmar que CASV/0.4 possui tiling espacial bounded, quatro transforms
reversíveis reais, escolha T por tile, receipts individuais, decoder
independente e reconstrução byte-exata em probes curtos RGB8/YUV10 e em um crop
real derivado de vídeo 8K.

Ainda não é correto afirmar que CASV/0.4:

- codificou um quadro ou vídeo 8K integral;
- inclui áudio;
- usa predição temporal;
- compreende semanticamente objetos de vídeo natural;
- vence zlib, zstd, FFV1, HEVC ou AV1 como classe;
- alcança compressão próxima de 100%;
- é formato comercial estabilizado.
