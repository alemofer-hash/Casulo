# Implementação do caminho estrutural de compressão

Data: 2026-09-09  
Estado: `LC3_STRUCTURAL_PATH_IMPLEMENTED_SHORT_PROBE_PASS`  
Resultado de compressão do probe: `NEGATIVE_NET_EXPANSION`

## Veredito direto

Os sete componentes solicitados foram implementados e atravessados por um
probe curto derivado do vídeo 8K real. O caminho é reversível, separa
explicitamente `base + dynamics + residual`, analisa MP4/HEVC, mede cada
candidate transform, reconstrói por um decoder independente e demonstra
autoridade causal T com mudança real de primitives invocadas.

O resultado honesto também é claro: esta primeira família estrutural **ainda
não comprime o probe líquido**. Ela reduziu os payloads em 0,290958%, mas o
archive completo ficou 1,820171% maior após contabilizar IR, TCAP, policy,
receipts, traces e índices. A arquitetura passou; a hipótese de grande
compressão não passou neste probe e não foi declarada.

## Matriz dos sete requisitos

| Requisito | Implementação | Gate executado | Estado |
|---|---|---|---|
| 1. IR reversível | `structural_ir.py`; cobertura exata, hashes, inverses e plan hash | validação encoder + decoder | PASS |
| 2. base + dinâmica + residual | partições disjuntas e exaustivas no `plan.json` | sete segmentos reclassificados e reconstruídos | PASS |
| 3. MP4/HEVC | parser de boxes, hvcC, tabelas e NAL headers | fonte 18.381.885.157 B, 33 boxes, `hev1` | PASS |
| 4. transforms causais mensuráveis | cinco candidates, tempos, tamanhos, operações e política de família | 19 vs 7 invocações após mutação T | PASS |
| 5. reconstrução independente | decoder stdlib-only sem imports do encoder/transforms/T runtime | dois archives reconstruídos para o mesmo SHA | PASS |
| 6. autoridade causal T | T/2 -> AST -> semântica -> IR -> grafo -> TCAP -> Rust runtime | source/IR/TCAP/trace/trabalho mudaram | PASS |
| 7. probes curtos | probe MP4 de 4 MiB de mídia derivado da fonte real | execução completa em segundos | PASS |

## Fonte realmente inspecionada

```text
C:\CasuloLab\incoming\000_10sec_8K.mp4
bytes:   18.381.885.157
SHA-256: 68011a473a3c3f963dfe716620991eb92d87473e9a7204ae323a1dceb0502d24
```

O hash da fonte é herdado de receipt aceito anterior e não foi recalculado pelo
probe curto. A análise atual fez leituras seek-based limitadas.

Estrutura observada:

- top-level: `ftyp` 28 bytes, `mdat` 18.381.875.083 bytes e `moov` 10.046 bytes;
- 33 boxes no total;
- sample entry `hev1`;
- `hvcC` version 1, profile IDC 4, level IDC 183, NAL length de 4 bytes;
- um VPS, um SPS e um PPS;
- 600 sample sizes, 600 offsets `co64` e uma entrada `stsc`;
- 64 amostras uniformemente distribuídas tiveram apenas headers NAL lidos;
- tipos NAL observados: 63 do tipo 1, um do tipo 19 e 64 do tipo 39;
- IRAP observado na amostra zero;
- entropia amostral do `mdat`: 7,947413994 bits/byte.

A entropia alta é compatível com um bitstream HEVC já comprimido. Ela não
prova incompressibilidade matemática, mas explica por que transforms bytewise
simples encontram apenas ganho marginal.

## Probe final

Evidência append-only:

```text
C:\CasuloLab\campaigns\2026-09-09-structural-architecture-probe-attempt8
```

O probe mantém `ftyp`, uma prefixo de 4 MiB do `mdat` com header corrigido e o
`moov`. Ele é derivado de bytes reais, mas seus sample offsets originais não
são reescritos; por isso é explicitamente `scientific_eligible=false` e
`playable_not_claimed=true`. Seu propósito é exercer o caminho, não substituir
o vídeo integral.

```text
probe bytes:   4.204.386
probe SHA-256: 8f3fe0bb427e04cae2004d53f7b1159f42b585e5f1b1525b4e75cc9440992b69
segmentos:     7
base:          3 headers
dynamics:      2 chunks mdat + moov transformados
residual:      payload ftyp literal
```

## Resultado quantitativo

### Política T padrão

```text
T calls:                          14 (7 plan + 7 decide)
primitive candidates executadas: 19
payload bytes únicos:             4.192.153
redução de payload:               12.233 bytes = 0,2909580614%
archive completo:                 4.280.913 bytes
archive/source:                   1,0182017065
mudança líquida:                  +1,8201706504%
transform trace:                  4 raw + 3 shuffle4-zlib
reconstrução independente:        PASS
```

### Mutação T `force raw`

```text
T calls:                          14
primitive candidates executadas: 7
bytes de candidates:              4.204.386 (contra 12.604.330)
transform trace:                  7 raw
archive completo:                 4.263.714 bytes
reconstrução independente:        PASS
```

O archive force-raw ser menor neste probe não contradiz a redução de payload
da política padrão: o custo fixo de policy/TCAP/receipts é grande diante de 4
MiB. Isso revela que o próximo juiz precisa considerar custo total amortizado,
e não somente o menor payload local.

## Causalidade T

Alterar apenas a source T mudou todos os observáveis exigidos:

- source T hash;
- typed IR hash;
- TCAP hash;
- família de candidates;
- número de primitive calls (19 -> 7);
- bytes de candidates produzidos (12.604.330 -> 4.204.386);
- transform trace;
- archive bytes e hash.

Os dois resultados restauraram o mesmo probe. A política, portanto, altera
causalmente a execução e não apenas um receipt posterior.

Identidades da política padrão:

```text
source T: c1b32fca3b3fc4f19429fdb337b00a58ab5a759459f7b5b539bbd3e92df5049e
typed IR: 1b51ff5defbff08125386cc634148d566872b7bedfa4ecf4f32ec420deb3e022
TCAP:     fd243564046cf0af2053451802f52933dbcebeba69debc8d04d658318cbc1641
```

## Reconstrução independente

O processo independente verificou 14 receipts e sete segmentos, produziu
4.204.386 bytes e obteve novamente:

```text
8f3fe0bb427e04cae2004d53f7b1159f42b585e5f1b1525b4e75cc9440992b69
```

Ele não importa o encoder, a implementação forward das transforms nem o
runtime T. Também verifica os observables T preservados contra seus receipts e
contra os candidates/transform realmente publicados.

## Falha encontrada e preservada

`attempt3` falhou com `sample range exceeds source`. O parser profundo passou a
validar as tabelas do `moov`; como o probe corta o `mdat`, offsets válidos para
o vídeo integral deixam de ser válidos nele.

A correção não afrouxou a análise científica: fonte normal permanece estrita.
Somente um probe marcado não científico permite registrar o diagnostic e
continuar sua prova de transporte. Essa divergência está preservada; não foi
apagada ou reclassificada.

## Testes

Gate focal final:

```text
68 passed
```

Inclui compressão genérica anterior, transforms e inverses, parser MP4/HEVC,
CDC determinístico, corrupção de payload, reconstrução independente, pipeline
T/2, runtime Rust, receipts e autoridade crítica T.

Testes específicos estruturais:

```text
13 passed
```

## Hashes finais

```text
MANIFEST.json  4798362fb6610eda8c7a4f31c18084bdb28544f14f7fe1f4e6dc332b751e0056
analysis.json  ddaa308816da7ca58d50fb405513339a531dee9a903ed50afb91dfe5316229aa
report.md      0577b6187c73779a43ac25f0846b5abf928169f2319f4fa5b0baa770f39bd011
code provenance 5fbf05cb76e79bbc1dff86e1432faeeeb0e6b97f42b7d0fc4f77dcd70272087c
protocol.json  4c3c4df2f4a3835bcd1d5752481e2f1fae026939431df5db5e1cda422b3171eb
default zip    038cf0c33fb0e6b7b11d24219865eef8e197f5af459a0cc47217fd99b6c01693
force-raw zip  84cb779f4bd406f06b46663e3f8d68911c89d4cd5634ed624ea410fd1db18bd3
```

## O que está pronto e o que não está

Pronto:

- arquitetura verificável que não esconde residual ou estado;
- análise estrutural real de MP4/HEVC;
- transform IR e container;
- T causal antes do trabalho e antes da persistência;
- decoder independente;
- instrumentação curta e reproduzível.

Não pronto:

- compressão forte de bitstream HEVC;
- modelagem inter-frame/GOP bit-exact;
- parsing e re-emissão CABAC;
- dicionários aprendidos content-addressed;
- primitives SIMD/Rust no caminho quente;
- política de custo global e amortização;
- execução estrutural integral de 18,38 GB;
- prova contra codecs estabelecidos;
- qualquer alegação próxima de 100%.

## Próximo gate inevitável

Antes de repetir o vídeo integral, o trabalho tecnicamente racional é:

1. criar um corpus de desenvolvimento separado do holdout;
2. adicionar análise completa de unidades de acesso/GOP sem decodificar pixels;
3. localizar redundância causal entre frames, parameter sets e metadata;
4. implementar dicionário e predictor com residual integral;
5. migrar prepasses aprovados para Rust/SIMD;
6. fazer T julgar custo total estimado, incluindo policy/IR/receipts;
7. executar probes crescentes de 64 MiB, 256 MiB e 1 GiB;
8. só então congelar protocolo para os 18,38 GB.

O estado científico atual é deliberadamente bifurcado:

```text
ARCHITECTURE_EXECUTION = PASS
LOSSLESS_RECONSTRUCTION = PASS
T_CAUSAL_AUTHORITY = PASS
BOUNDED_PROBE_NET_COMPRESSION = FAIL (1,820171% expansion)
FULL_8K_STRUCTURAL_RESULT = NOT_RUN
NEAR_100_PERCENT_CLAIM = NOT_AUTHORIZED
```
