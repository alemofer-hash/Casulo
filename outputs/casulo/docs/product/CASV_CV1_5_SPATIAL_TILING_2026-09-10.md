# CV1.5 — spatial tiling bounded e decisão T por tile

Estado: `PASS_SPATIAL_TILING_ENGINEERING_GATE_COMPACT_INDEX_PENDING`

## Resultado principal

CASV/0.4 tornou executável o caminho que CASV/0.3 recusava estruturalmente:
processar mídia 8K em working set limitado sem materializar um quadro inteiro.
A rota real agora é:

```text
FFmpeg stdout
→ stream canônico RGB8 ou YUV444P10LE
→ faixa bounded
→ tiles
→ quatro candidatos reversíveis fechados localmente
→ batch físico de decisões T independentes
→ commit da faixa
→ CASV/0.4
→ decoder stdlib-only
→ SHA-256 canônico integral
```

O gate de arquitetura passou. O gate de compressão competitiva ainda não.

## Implementação

- layout frame/plane/strip/tile sem alocação de frame;
- limites de 8 MiB por tile, 64 MiB por faixa e 64 MiB para a família de
  candidatos do encoder;
- transforms `DC_XOR_ZLIB`, `PAETH_ZLIB`, `CANONICAL_ZLIB` e `CANONICAL_RAW`;
- formato binário `CVT4`, tabela de tiles e manifesto hasheado;
- decoder independente bounded para RGB8 e `YUV444P10LE`;
- writer append-only com publicação atômica;
- integração FFmpeg por pipe direto e player incremental;
- `ProductiveTExecutor.execute_batch` e runtime Rust `--batch`;
- uma decisão semântica e um receipt por tile, apesar da invocação física
  amortizada por faixa;
- policy mutation T que força raw sem alterar writer ou decoder;
- CLI pack/inspect/verify/unpack/import/probe.

## Probe sintético corrigido

Evidência atual:

```text
C:\CasuloLab\campaigns\2026-09-10-casv-tiled-v04-synthetic-attempt2
```

Gates: 7/7 PASS. As quatro entradas reconstruíram exatamente. A mutação somente
T mudou todos os tiles para raw e manteve o hash canônico. Ruído incompressível
foi preservado como expansão e recebeu `REJECT` contra raw.

Selos:

```text
MANIFEST.json  cbd8c8679a196ff6869a76a3df9f2eb0920f110b75a50dd76185475dbf1a754e
SHA256SUMS     b0d0582a1b768f8e35cdb3db138d611b951f0879f387c3064f3f50859f4ce961
entradas       135
```

O probe de layout calculou um quadro 8K YUV10 em 102 registros e 1.632 tiles,
com faixa máxima de 2.097.152 bytes. Foi aritmética validada, não encode 8K.

Os casos geométricos sintéticos perderam para zlib global porque a divisão em
tiles destrói redundância de longo alcance e o manifesto domina arquivos muito
pequenos. Isso é um controle negativo útil, não falha de reversibilidade.

## Probe natural real

Fonte:

```text
C:\CasuloLab\incoming\000_10sec_8K.mp4
18.381.885.157 bytes
SHA-256 68011a473a3c3f963dfe716620991eb92d87473e9a7204ae323a1dceb0502d24
HEVC, 8192×4320, yuv444p10le, 60000/1001 fps
```

Derivação executada: crop 256×144 na origem, dois quadros, três planos
`YUV444P10LE`, sem raw intermediário.

| Grandeza | Bytes | Comparação com zlib global |
|---|---:|---:|
| raw canônico | 442.368 | — |
| zlib global do mesmo stream | 94.890 | referência |
| payloads dos 72 tiles | 83.650 | 11.240 menor / 11,845% |
| 18 registros completos | 86.170 | 8.720 menor / 9,190% |
| manifesto JSON | 16.271 | overhead |
| magic + footer | 56 | overhead |
| archive CASV/0.4 | 102.497 | 7.607 maior / 8,017% |

Decomposição dos registros: 1.368 bytes de cabeçalhos, 1.152 bytes de tabelas e
83.650 bytes de payload. O manifesto correspondeu a 15,875% do archive.

O achado causal é preciso: Paeth/DC por tile encontrou 11.240 bytes que o zlib
global não removeu do payload; o custo de formato apagou essa economia e
transformou o resultado líquido em derrota.

Distribuição escolhida por T:

```text
PAETH_ZLIB       65 tiles
DC_XOR_ZLIB       3 tiles
CANONICAL_ZLIB    4 tiles
```

Foram 72 decisões T, 18 invocações físicas em batch e 73 receipts incluindo o
juízo final. O decoder independente recompôs os 442.368 bytes e fechou:

```text
eb1c094a58e0c79aa7a75075c31638cd20b884a7526b0786bf16342730bc3aa8
```

Archive:

```text
9b078c113153f43cba2c7d4d73c848e23c995cce1cd81ce1efba83ca05c64945
```

Evidência interna selada:

```text
MANIFEST.json  feb5d6363497a9c29e6079f3b14a09752faa155ee26804e6f93494dae89226e0
SHA256SUMS     ecfb409d904c712806998869733394899095fa936fd953ed26143b81b7ea8727
entradas       40
```

`metric-recomposition-v2.json` recompõe esses tamanhos diretamente dos bytes
selados. Ele corrige semanticamente a nomenclatura antiga sem alterar o archive
ou o relatório original.

## Tentativa rejeitada preservada

`2026-09-10-casv-tiled-v04-real-crop-attempt1` parou no preflight porque o
argumento de hash esperado tinha um erro de transcrição. Nenhum workload foi
iniciado e nenhum archive foi publicado. A tentativa contém receipt explícito;
o valor digitado incorretamente não foi inventado retroativamente.

## Validação

```text
suíte focal CASV/T                        56 passed
teste red/green da semântica de métricas 2 failed antes / 2 passed depois
runtime Rust                             cargo test PASS
runtime Rust release                     cargo build --release --locked PASS
ruff focal                               PASS
rustfmt                                  PASS
compileall                               PASS
probe sintético corrigido                7/7 gates PASS
round-trip real                          PASS
```

Uma invocação anterior de `pytest --basetemp` encontrou apenas o diretório pai
temporário ausente: 13 testes sem `tmp_path` passaram e 43 setups não rodaram.
Depois de criar o pai local, a mesma suíte terminou 56/56 PASS. Uma tentativa
de validar fontes T/2 com o CLI legado T/1 também foi descartada como comando
incompatível; os builders T/2 e o runtime Rust executaram as policies nos gates.

## Interpretação honesta

O resultado é positivo para a arquitetura e misto para compressão:

- **positivo:** o gargalo de memória de um quadro 8K foi removido por desenho;
- **positivo:** transforms espaciais reduziram o payload real além de zlib;
- **positivo:** T governou causalmente cada commit de tile;
- **negativo:** o archive final ficou 8,017% maior que zlib global;
- **negativo:** não há predição temporal nem compreensão de objetos;
- **negativo:** decodificar o crop pela fonte 8K levou 77,164 s;
- **não testado:** quadro/vídeo 8K integral, áudio e baselines maduros.

O `ACCEPT` histórico de T compara o archive a 442.368 bytes raw. Não autoriza a
frase “T venceu zlib”; o archive não venceu.

## Próximo gate inevitável

1. CASV/0.5 com índice binário compacto e metadados globais não repetitivos;
2. policy T recebendo custo marginal **e** custo total do container;
3. delta temporal entre tiles homólogos, com keyframes e fallback exato;
4. preditor numérico para amostras 10-bit, não apenas bytewise;
5. escolha conjunta de tamanho de tile/strip em protocolo pré-congelado;
6. comparação em clips naturais curtos contra zlib, zstd, FFV1 e x265 lossless;
7. somente após o archive vencer consistentemente, ampliar resolução e duração.

Áudio continua reservado a uma versão audiovisual posterior.
