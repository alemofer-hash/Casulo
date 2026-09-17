# CV1.4 — programa segmentado `base + dinâmica + residual`

Estado: `PASS_CAUSAL_PROGRAM_ENGINEERING_GATE_SPATIAL_TILING_PENDING`

## Resultado principal

CASV/0.3 executa pela primeira vez a gramática causal dentro do container
streaming. O caminho implementado é:

```text
FFmpeg stdout
→ mídia canônica RGB8 ou YUV444P10LE
→ grupos de quadros
→ inferência de base e dinâmica
→ render determinístico
→ residual XOR exato
→ três custos observados
→ decisão T antes do commit
→ CASV/0.3
→ decoder independente
→ SHA-256 integral
```

Não há MP4/HEVC encapsulado nem arquivo raw intermediário na rota FFmpeg. O
renderer de 10 bits é first-party e opera sobre três planos Y/U/V. O player
0.3 usa o decoder independente e envia os quadros por pipe ao ffplay.

## O que foi implementado

- IR de segmento com materiais, retângulos e movimento linear;
- renderer nativo RGB8 e `YUV444P10LE` planar;
- envelope binário `CVG3 = CVB3 + CVD3 + residual`;
- residual zero ou XOR comprimido, sempre com fechamento exato;
- proposer bounded com até 64 materiais, 32 tracks e 1.000.000 pixels;
- container CASV/0.3 forward-only, frame-aligned e append-only;
- decoder stdlib-only que não importa encoder, IR, proposer nem T;
- extração seletiva e player incremental em duas passagens;
- `casv-program-pack`, `inspect`, `verify`, `unpack`, `extract`, `import` e
  `probe`;
- adapter FFmpeg compartilhado com timeout, stderr limitado e commit somente
  após exit code zero;
- policy mutation exclusivamente T demonstrando mudança causal de storage.

## Probe sintético selado

Evidência:

```text
C:\CasuloLab\campaigns\2026-09-10-casv-program-v03-synthetic-attempt1
```

| Caso | Raw canônico | Programa | Zlib direto | Modo T | Archive |
|---|---:|---:|---:|---|---:|
| RGB estruturado | 186.624 | 450 | 534 | `GENERATIVE_EXACT` | 5.180 |
| YUV10 estruturado | 110.592 | 224 | 350 | `GENERATIVE_EXACT` | 4.037 |
| ruído determinístico | 62.208 | 62.308 | 62.234 | `CANONICAL_RAW` | 65.083 |
| RGB com policy mutada | 186.624 | 450 | 534 | `CANONICAL_RAW` | 191.359 |

O programa economizou 15,73% do payload contra zlib no RGB e 36,00% no YUV10
estruturados. Esses números são propriedades de fixtures geométricas triviais,
não evidência de vídeo natural.

No ruído, nenhum candidato comprimiu. T escolheu raw e o juiz retornou
`REJECT`; o archive completo expandiu 4,62% por causa do manifesto. A falha de
custo foi preservada.

A mutação `compression_casv_force_raw.t` mudou TCAP e os três storage modes sem
alterar encoder ou source. As duas reconstruções produziram o mesmo SHA-256
canônico. Isso demonstra causalidade de T na seleção; não torna T autora do
proposer ou do renderer.

Selos:

```text
MANIFEST.json  1edb78b12507353ea33a50638d5483c246aaee2051d8dee8590485a5e8eea7d4
SHA256SUMS     eed9b8948a76c9c8d5d1d92544e1a14955e882b55407653f4cb99a9e81dde3e7
entradas       97/97 PASS
```

## Probe natural derivado — dois quadros

Fonte validada:

```text
C:\CasuloLab\incoming\000_10sec_8K.mp4
18.381.885.157 bytes
SHA-256 68011a473a3c3f963dfe716620991eb92d87473e9a7204ae323a1dceb0502d24
HEVC, 8192x4320, yuv444p10le, 60000/1001 fps
```

Derivação: crop 256×144 em 0,0, dois quadros, `YUV444P10LE` preservado.

| Métrica | Valor |
|---|---:|
| bytes canônicos | 442.368 |
| SHA-256 canônico | `eb1c094a58e0c79aa7a75075c31638cd20b884a7526b0786bf16342730bc3aa8` |
| programa | 93.569 bytes |
| zlib direto, mesmo bloco | 94.890 bytes |
| economia causal de payload | 1.321 bytes / 1,392138% |
| pixels previstos exatamente | 504 / 73.728 / 0,683594% |
| bytes não zero no residual | 216.143 / 442.368 / 48,860451% |
| archive CASV/0.3 | 99.130 bytes |
| archive + autoridade | 137.640 bytes |
| tempo FFmpeg/pipe | 21,090305 s |

T escolheu `GENERATIVE_EXACT`; o decoder independente fechou o mesmo hash
canônico das rotas CV1.1 e CV1.3.

O mecanismo venceu o zlib no payload, mas não venceu o melhor archive histórico
da mesma derivação: o CASV/0.1 zlib tinha 98.485 bytes. O 0.3 ficou 645 bytes
maior, ou 0,654922%, porque a proveniência segmentada ainda não amortizou. Ele
ficou 3.623 bytes menor que o CASV/0.2 de sete segmentos, comparação que também
inclui diferença de segmentação. Nenhuma delas é apresentada como comparação
contra HEVC.

Evidência e selos:

```text
C:\CasuloLab\campaigns\2026-09-10-casv-program-v03-real-crop-attempt1
archive        388ea31c143e78be05c40abe5898cc85380a5c14c871af44fa7513087d3d259a
MANIFEST.json  3b53660dae30e9f85335a7de2e45dcb175fce7b852e7c680bcb857f653a12f26
SHA256SUMS     31a310d031c9120cb2534bacb465c8c71ae085299a63e185e291e346cadeaa6f
entradas       21/21 PASS
```

## Probe natural derivado — oito quadros

Mesma fonte e crop, agora oito quadros em um único segmento.

| Métrica | Valor |
|---|---:|
| bytes canônicos | 1.769.472 |
| SHA-256 canônico | `afb40c79c9a6d3bb2b6a9a73800da4eb9a9a9a183ed3761eac2ded71d4d67b98` |
| programa | 357.828 bytes |
| zlib direto, mesmo bloco | 363.549 bytes |
| economia causal de payload | 5.721 bytes / 1,573653% |
| pixels previstos exatamente | 2.324 / 294.912 / 0,788032% |
| bytes não zero no residual | 818.083 / 1.769.472 / 46,233170% |
| archive CASV/0.3 | 363.402 bytes |
| archive + autoridade | 401.922 bytes |
| redução do archive contra raw canônico | 79,462687% |
| tempo FFmpeg/pipe | 126,001937 s |

O archive inteiro ficou 147 bytes menor que o payload zlib nu. Isso mostra que
o custo fixo começou a amortizar nessa janela, mas não constitui comparação com
um container zlib equivalente nem com codecs maduros.

O custo de encode é um resultado negativo importante. Decodificar oito quadros
da fonte 8K antes do crop levou 126 s, e o proposer atual faz busca
`O(candidatos × pixels)`. Não existe base para chamar esse caminho eficiente.

Evidência e selos:

```text
C:\CasuloLab\campaigns\2026-09-10-casv-program-v03-real-clip8-attempt1
archive        4a6f7a82745f5690c77e5115033842a844c2ab698de06c7afc09233356f34d17
MANIFEST.json  0cac028604c13a56d0bffe981abec4e76e330cddae0f50eed3f1c5c52858a871
SHA256SUMS     14718c895ab7d5d260803adc4ec436b2e75ea18fe9394be64a185f840dda85ab
entradas       21/21 PASS
```

## Validação

```text
IR + programa CASV/0.3                   17 testes coletados
regressão de compressão                  90 passed
pipeline T e TCAP                        61 passed, 42 subtests passed
total das duas suítes não sobrepostas    151 passed, 42 subtests passed
ruff focal                               PASS
py_compile focal                         PASS
probe sintético                          7/7 gates PASS
round-trip real 2 e 8 quadros            PASS
manifestos                               97/97, 21/21 e 21/21 PASS
```

## Interpretação honesta

O caminho deixou de ser apenas `raw/zlib`: o programa causal foi serializado,
selecionado por T, decodificado por implementação independente e venceu o zlib
direto por 1,39–1,57% nos dois recortes naturais medidos. Esse é um sinal
positivo de transformação reversível.

Ainda não é evidência de compressão de vídeo natural como classe. O programa
não encontrou tracks no recorte real; ele atuou essencialmente como preditor de
background mais residual XOR. Menos de 0,8% dos pixels foram explicados
integralmente, o residual domina e o custo de encode é alto. A hipótese de
reconstrução semântica rica continua aberta.

Não foram executados vídeo integral, resolução 8K no encoder CASV/0.3, áudio,
benchmark energético, Cloud, USB, owner/public ou release.

## Próximo gate inevitável

1. spatial tiling frame-aligned para um quadro 8K caber em memória bounded;
2. proposer linear por histogramas/bounding boxes, sem 64 varreduras completas;
3. preditores reversíveis por tile e plano: DC/gradiente, delta temporal e
   movimento inteiro;
4. T escolhendo a família por tile com custo integral de metadados;
5. reconstrução independente e corrupção localizada;
6. clips naturais curtos pré-congelados contra zlib, zstd, FFV1 e x265 lossless;
7. somente depois, aumento gradual de resolução e duração.

Áudio permanece reservado a uma versão audiovisual posterior.
