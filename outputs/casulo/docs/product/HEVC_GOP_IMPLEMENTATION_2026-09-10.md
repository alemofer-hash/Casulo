# Implementação HEVC GOP — evidência de 2026-09-10

Estado: `LC3_GOP_CAUSAL_PATH_SHORT_PROBE_PASS_COST_REJECTED`

## Resultado principal

O caminho pedido foi implementado e executado de ponta a ponta: IR reversível,
partição explícita `base + dynamics + residual`, análise completa das
fronteiras MP4/HEVC, candidate inter-amostra mensurável, reconstrução
independente, autoridade causal T e probe real curto.

O resultado de compressão líquida foi negativo e está preservado. No corpus de
60.229.738 bytes, os payloads selecionados economizaram 58.949 bytes, mas o
archive completo adicionou 62.965 bytes de estrutura e evidência. Resultado:
4.016 bytes de expansão, ou `+0,0066678025%`. O juiz T retornou `REJECT`.

## Fonte e escopo executado

| Item | Valor |
|---|---:|
| Fonte real | `C:\CasuloLab\incoming\000_10sec_8K.mp4` |
| Fonte | 18.381.885.157 bytes |
| SHA-256 aceito | `68011a473a3c3f963dfe716620991eb92d87473e9a7204ae323a1dceb0502d24` |
| Mapa integral | 600 samples; 1.200 NAL units; 3 grupos GOP |
| Headers NAL lidos no scan | 7.200 bytes |
| Corpus executado | samples 0 e 1, completas, iniciado em IRAP |
| Corpus | 60.229.738 bytes |
| SHA-256 do corpus | `747498e7a5357860e78d5a49f8a1ee03cd072acbb1a9bd81a2f6dc84505a4c59` |
| GOP completo? | não |
| Elegível como prova do vídeo? | não |

O scan percorreu todas as 600 amostras e 1.200 NALs usando apenas prefixos e
headers. A transformação foi deliberadamente limitada a duas amostras para não
reativar uma carga longa antes de existir um caminho streaming.

## Arquitetura executada

| Camada | Código | Responsabilidade |
|---|---|---|
| sample layout | `mp4_hevc.py::primary_hevc_sample_layout` | offsets e tamanhos completos do track |
| access units/GOP | `hevc_gop.py::scan_hevc_access_units` | fronteiras NAL e agrupamento IRAP |
| corpus | `hevc_gop.py::build_sample_aligned_corpus` | cópia exata de samples completas |
| transforms | `gop_transforms.py` | raw, zlib e XOR reversível |
| autoridade | `gop_authority.py::GOPTAuthority` | plan, decide e judge T |
| archive | `gop_archive.py::pack_gop_corpus` | IR, payloads e evidência |
| decoder | `independent_gop.py::reconstruct_gop_independently` | verificação e inversa sem importar o encoder |
| orquestração | `gop_probe.py::run_gop_probe` | mutação causal e selo append-only |
| CLI independente | `tools/verify_casulo_gop.py` | verificação portátil do archive |

## Contabilidade da partição

```text
base       =        24 bytes
dynamics   = 29.128.594 bytes
residual   = 31.101.120 bytes
total      = 60.229.738 bytes
```

A soma é exata. Os 24 bytes de base são quatro prefixos de comprimento e
quatro headers HEVC. A dynamics é a única NAL VCL persistida por zlib; os três
corpos restantes são residual raw.

## Transform inter-amostra

O segundo corpo VCL, com 29.128.594 bytes, foi submetido a três candidates:

| Candidate | Bytes | Diferença para raw | Selecionado? |
|---|---:|---:|---|
| raw | 29.128.594 | 0 | não |
| XOR de 1 MiB contra VCL anterior + zlib | 29.128.928 | +334 | não |
| zlib | 29.069.645 | -58.949 | sim |

O candidate causal inter-frame foi realmente executado e sua inversa foi
testada, mas perdeu até para raw. Isso falsifica a versão ingênua da hipótese:
XOR bytewise entre bitstreams HEVC adjacentes não capturou a redundância
temporal útil. O zlib isolado reduziu esse corpo em `0,202375%`.

## Autoridade causal de T

A política padrão executou nove invocações de primitive e selecionou três
entradas raw e uma zlib. A mutação exclusivamente em T `force raw` executou
quatro invocações e selecionou quatro entradas raw.

Mudaram:

- source T e TCAP;
- famílias de candidates;
- quantidade e bytes de trabalho;
- trace de transforms;
- tamanho e hash do archive.

Não mudaram o corpus nem o oráculo de reconstrução. Ambos os archives voltaram
ao mesmo SHA-256. A causalidade está demonstrada apenas nessas superfícies.

## Números finais

| Métrica | Política T padrão | Force raw |
|---|---:|---:|
| Archive | 60.233.754 B | 60.283.111 B |
| Razão archive/corpus | 1,0000666780 | 1,0008861569 |
| Mudança líquida | +4.016 B | +53.373 B |
| Primitives | 9 | 4 |
| Transforms | 3 raw + 1 zlib | 4 raw |
| Reconstrução independente | PASS | PASS |
| Receipts T plan/decide | 8 | 8 |
| Julgamento de custo | REJECT | REJECT |

A política padrão produziu um archive 49.357 bytes menor que force raw, mas
isso não a tornou menor que a fonte.

## Verificação

```powershell
ruff check src/casulo/compression/hevc_gop.py src/casulo/compression/gop_transforms.py src/casulo/compression/gop_authority.py src/casulo/compression/gop_archive.py src/casulo/compression/independent_gop.py src/casulo/compression/gop_probe.py tests/product/test_gop_compression.py tools/verify_casulo_gop.py
python -m pytest -q tests/product/test_gop_compression.py tests/product/test_structural_compression.py
python -m pytest -q tests/product/test_lossless_compression.py tests/product/test_structural_compression.py tests/product/test_gop_compression.py tests/product/test_t_v2_semantics.py tests/product/test_t_v2_runtime.py tests/product/test_t_v2_adversarial.py tests/product/test_t_v2_rust_conformance.py tests/product/test_t85_critical_authority.py
python tools/verify_casulo_gop.py C:\CasuloLab\campaigns\2026-09-10-hevc-gop-causal-probe-attempt4\default-policy.casulo-gop.zip
python tools/verify_casulo_gop.py C:\CasuloLab\campaigns\2026-09-10-hevc-gop-causal-probe-attempt4\force-raw-policy.casulo-gop.zip
```

Resultados: lint PASS; 19 testes focados PASS; 74 testes integrados PASS; os
dois verificadores independentes PASS; manifesto 112/112 válido.

## Evidência selada

Diretório:

```text
C:\CasuloLab\campaigns\2026-09-10-hevc-gop-causal-probe-attempt4
```

| Artefato | SHA-256 |
|---|---|
| `MANIFEST.json` | `904795b0c09b67b34b8c9a6c3d92477076eb7111002d02a90b9d48baf90f460f` |
| `analysis.json` | `9f5f232ea51eac5de9ff60730eab4c72b42dd3281ec3aff558e9318d6bc8919a` |
| `report.md` | `fe3084b7e730547ea960c4d879e9567152fc5066e67c32c41823ff585d8bcddf` |
| archive padrão | `d90ebf124ae297b1bfd75cd50c81bfd200b0e8fda2a4ca34e2f4bda1f3a754e5` |
| archive force raw | `e550fbda27b1d5beb63fd8a73ef4ae837b1a2132309f4f686ecbb01afe4f4cec` |

## Conclusão e próximo gargalo

O caminho arquitetural existe e é verificável. O algoritmo v1 não entregou
compressão líquida no corpus; isso não é incompletude do teste, mas resultado
negativo da família de transforms atual.

O próximo passo não é rodar 18,38 GB com a mesma matemática. É primeiro:

1. tornar encoder e decoder streaming com working set rígido;
2. modelar parameter sets e slice headers sem alterar CABAC;
3. construir relações reais de referência entre access units;
4. testar dicionários treinados somente no passado do GOP;
5. repetir probes de 64 MiB e 256 MiB;
6. avançar a um GOP completo apenas se o custo total se aproximar de ganho.

Claims autorizados: arquitetura GOP/NAL v1, round-trip exato, causalidade T e
resultado líquido negativo no probe. Claims proibidos: ganho no vídeo inteiro,
compressão próxima de 100%, compressão de pixels ou superioridade sobre HEVC.
