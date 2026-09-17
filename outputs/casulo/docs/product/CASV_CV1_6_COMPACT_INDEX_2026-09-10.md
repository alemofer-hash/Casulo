# CV1.6 — índice compacto e juízo T sobre o arquivo inteiro

Estado: `PASS_COMPACT_INDEX_BOUNDED_REAL_CROP_TEMPORAL_PENDING`

## Resultado principal

CASV/0.5 removeu o overhead que anulava o ganho espacial do CASV/0.4. No mesmo
stream canônico real já selado, o arquivo final — incluindo todos os
cabeçalhos, tabelas, hashes e footer — ficou menor que zlib global:

| Grandeza | Bytes | Diferença contra zlib |
|---|---:|---:|
| raw canônico | 442.368 | — |
| zlib nível 9 do stream inteiro | 94.890 | referência |
| payload selecionado dos tiles | 83.650 | −11.240 / −11,8453% |
| records + tabelas + payload | 84.802 | −10.088 / −10,6313% |
| CASV/0.5 completo | **84.958** | **−9.932 / −10,4669%** |

O overhead total do arquivo sobre o payload foi 1.308 bytes: 792 de headers de
18 registros, 360 de 72 entradas de tile e 156 fixos. O CASV/0.5 ficou
17,1117% menor que o CASV/0.4 de 102.497 bytes sobre exatamente os mesmos
pixels.

Contra o raw canônico, a redução foi 80,7947%. Esse número não deve ser
comparado ao MP4/HEVC de origem: o MP4 contém outro recorte contratual,
compressão temporal, container e possivelmente outros streams.

## O que foi executado

Fonte histórica preservada:

```text
C:\CasuloLab\incoming\000_10sec_8K.mp4
18.381.885.157 bytes
SHA-256 68011a473a3c3f963dfe716620991eb92d87473e9a7204ae323a1dceb0502d24
HEVC 8192×4320, yuv444p10le, 60000/1001 fps
```

A execução 0.5 não decodificou novamente os 18,38 GB. Ela começou no archive
CASV/0.4 selado, SHA-256
`9b078c113153f43cba2c7d4d73c848e23c995cce1cd81ce1efba83ca05c64945`,
reconstruiu-o com decoder independente e reempacotou exatamente:

```text
2 frames × 3 planos × 256 × 144 × 2 bytes = 442.368 bytes
SHA-256 eb1c094a58e0c79aa7a75075c31638cd20b884a7526b0786bf16342730bc3aa8
```

Portanto, a classe de prova é
`REAL_MEDIA_DERIVED_FROM_SEALED_CASV_0_4_ARCHIVE`, e não “novo decode 8K”. O
hash canônico foi igual na origem 0.4, no arquivo intermediário, no encoder 0.5
e no decoder 0.5.

## Arquitetura entregue

- container binário CASV/0.5 sem manifesto JSON embutido;
- geometria deduzida, entradas de tile de 5 bytes e headers de record de 44;
- writer forward, working set limitado por faixa e publicação atômica;
- quatro candidatos exatos: raw, zlib, DC/XOR+zlib e Paeth+zlib;
- decoder independente stdlib-only com limites contra expansão;
- CLI pack, inspect, verify, unpack, FFmpeg direct import, repack 0.4→0.5 e
  probe;
- player por pipe com verificação completa antes do segundo passe;
- importação FFmpeg direta testada sem raw intermediário;
- hashes do encoder, decoder, tile IR, adapter T, executor T, policy e runtime;
- baseline declarado como zlib RFC 1950 nível 9, runtime 1.3.1;
- T decide cada tile antes do commit e julga o custo do candidato completo
  antes da publicação.

Distribuição real escolhida por T:

```text
PAETH_ZLIB       65
DC_XOR_ZLIB       3
CANONICAL_ZLIB    4
```

Foram 72 decisões de storage, 18 invocações físicas em batch e 73 receipts ao
incluir o juízo final. O TCAP executado foi:

```text
4b1bfb803e58749502a94408d2c9608b9c46ebf4ee1d493216eb7fd4c2914b0c
```

O archive final foi:

```text
84.958 bytes
SHA-256 74ee0b4e85869b8f4ead977bfa0f89e6d42f3d44059c463fa661ce7684fc5368
```

## Custo da prova, separado do produto

Os artifacts externos de autoridade ocupam 191.958 bytes. Archive mais
autoridade somam 276.916 bytes: ainda 37,4014% menores que o raw, porém
191,8284% maiores que o zlib. Esses artifacts não são necessários para
decodificar o vídeo; são o custo de auditoria detalhada deste experimento.

Consequentemente há dois resultados distintos:

- `PRODUCT_BITSTREAM`: venceu zlib em 10,4669% neste recorte;
- `FULL_FORENSIC_BUNDLE`: perdeu para zlib por 191,8284%.

Nenhum deles pode ser ocultado. Uma futura distribuição pode manter apenas a
âncora criptográfica no archive e arquivar receipts fora da mídia, mas a prova
atual preserva tudo.

## Regressões e tentativas preservadas

O probe sintético `attempt1` falhou no gate econômico porque o fixture de
blocos repetidos era extraordinariamente favorável ao zlib global: 177 bytes
contra 1.796 no CASV. Isso foi preservado, não reclassificado.

O fixture foi corrigido em uma nova tentativa para exercer uma rampa espacial,
o domínio causal do Paeth, sem fingir vídeo natural. Nele:

```text
raw                 221.184 bytes
zlib global         221.260 bytes
CASV/0.5             19.992 bytes
```

A mutação exclusivamente T forçou raw e impediu publicação; ruído
incompressível também foi rejeitado e preservado. O fixture sintético serve
somente como regressão de transforms e policy.

Durante a integração, testes descobriram que o player esperava
`canonical_media` ausente no envelope do verificador e que um teste de
independência procurava um substring amplo demais. Ambos foram corrigidos antes
do selo final. Tentativas anteriores permanecem append-only; a evidência final
é `attempt5` sintética e `attempt4` real.

## Evidência final

Sintética:

```text
C:\CasuloLab\campaigns\2026-09-10-casv-compact-v05-synthetic-attempt5
MANIFEST.json  73cec6730b2fcd01626ecfe4d070897c163b3fffd3c97ef31b544cc990c82ef5
SHA256SUMS     c6ec0f34753f421bac010a3b231795582fc6921bd3f002d05944352e4306a41e
entradas       147
```

Real derivada:

```text
C:\CasuloLab\campaigns\2026-09-10-casv-compact-v05-real-crop-repack-attempt4
CAMPAIGN_MANIFEST.json  a919c577b9dc72b26c9975287318745f69aa5f7c99fe5a1cf316ae82ed9ec6ce
CAMPAIGN_SHA256SUMS     f93237a73076b15258cd2599979ee22559c5bf7864077e54384067740b5ac18e
entradas                48
```

Validação independente dos manifests: 147/147 e 48/48 arquivos presentes,
tamanhos e SHA-256 corretos. Os sete hashes de implementação do relatório
coincidiram com o worktree no momento do selo.

## Validação

```text
CASV integral                         78 passed
compact + importação FFmpeg focal     19 passed
Productive T batch                     3 passed
runtime Rust                          cargo test PASS
ruff nas superfícies alteradas        PASS
compileall                            PASS
probe sintético final                 7/7 gates PASS
repack real                           8/8 gates PASS
CLI inspect/verify real               PASS
```

## Leitura honesta

O avanço é real e delimitado: pela primeira vez nesta trilha, o arquivo CASV
completo venceu o baseline zlib de fluxo inteiro em pixels derivados de vídeo
real, preservando o SHA-256 canônico. A causa é verificável: transforms
espaciais economizaram 11.240 bytes e o índice compacto consumiu apenas 1.308.

Isso ainda não prova:

- vantagem em vídeo natural como classe;
- vantagem contra o HEVC original ou codecs lossless maduros;
- encode de frame ou vídeo 8K integral;
- compressão temporal;
- áudio;
- compressão próxima de 100%;
- custo computacional competitivo;
- generalização para outras cenas.

O próximo gate inevitável é CASV/0.6: delta temporal por tiles homólogos,
keyframes/fallback exatos, protocolo de clips pré-congelado e comparação contra
zlib, zstd, FFV1 e x265 lossless. Só depois se amplia resolução e duração.
