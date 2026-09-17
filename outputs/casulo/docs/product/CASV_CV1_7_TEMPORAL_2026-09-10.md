# CV1.7 — predição temporal exata e confronto com codecs maduros

Estado: `TEMPORAL_PATH_PASS_NATURAL_SIGNAL_REJECTED`.

## Resultado principal

CASV/0.6 foi implementado como formato binário próprio, reversível e limitado
em memória. O caminho temporal foi executado, T decidiu causalmente, keyframes
foram aplicados e um decoder independente reconstruiu cada byte canônico.

No clip natural real preservado, porém, a hipótese temporal mais simples
falhou: entre 252 tiles onde havia quadro anterior, T escolheu **zero**
candidatos temporais. A política agiu corretamente porque os deltas temporais
eram maiores que os preditores espaciais.

O arquivo CASV ainda venceu zlib, mas perdeu para zstd, x265 lossless e FFV1.
Logo, o gate de engenharia passou e o gate competitivo natural foi rejeitado.

## Fonte real delimitada

- origem imediata: CASV/0.3 real selado, derivado do vídeo 8K público já
  adquirido;
- archive fonte: 363.402 bytes;
- SHA-256 do archive fonte:
  `4a6f7a82745f5690c77e5115033842a844c2ab698de06c7afc09233356f34d17`;
- mídia canônica: 8 quadros, 256×144, `YUV444P10LE`, 60.000/1.001 fps;
- bytes canônicos: 1.769.472;
- SHA-256 canônico:
  `afb40c79c9a6d3bb2b6a9a73800da4eb9a9a9a183ed3761eac2ded71d4d67b98`;
- nenhum novo decode do MP4/HEVC ocorreu nesta campanha.

Trata-se de um crop curto de vídeo natural, não do vídeo 8K integral e não de
uma classe representativa de conteúdo.

## Protocolo congelado

Antes de produzir candidato ou baselines foram fixados:

- tile 64×48 e faixa de 48 linhas;
- keyframe a cada 8 quadros;
- zlib nível 9;
- zstd 1.5.7 nível 19, uma thread;
- FFV1 nível 3 em Matroska, uma thread;
- x265 lossless `medium` em Matroska, uma thread;
- reconstrução integral e SHA-256 idêntico como condição de validade.

SHA-256 do protocolo:
`36a1d26a18bf2fa6bb1d98a2b451640b3edf02c426b9fa2e6cd6857fb3dcaa37`.

## Tamanho observado

| Braço exato | Bytes | CASV relativo ao braço |
|---|---:|---:|
| canônico cru | 1.769.472 | 81,5423% menor |
| zlib 1.3.1 nível 9 | 363.549 | 10,1626% menor |
| zstd 1.5.7 nível 19 | 295.475 | 10,5349% maior |
| x265 lossless | 267.170 | 22,2454% maior |
| **FFV1 nível 3** | **195.574** | **66,9971% maior** |
| CASV/0.6 | 326.603 | — |

O menor baseline válido foi FFV1. A razão CASV/FFV1 foi 1,669971. Pela régua
congelada do projeto, o resultado é `NEGATIVE`, não `COMPETITIVE`.

O CASV/0.6 ficou 10,1263% menor que o CASV/0.3 anterior sobre a mesma mídia,
mas isso não muda a derrota contra o baseline maduro.

## Anatomia do CASV/0.6

- payload de tiles selecionados: 321.835 bytes;
- records completos: 326.443 bytes;
- overhead fixo: 160 bytes;
- archive: 326.603 bytes;
- SHA-256:
  `a09ef34ff4b8fa03b2c5fa174668d044b4e85a3e41af6bc452392deded75d9a3`;
- 72 records e 288 tiles;
- storage escolhido: 262 Paeth, 16 zlib, 10 DC/XOR, 0 temporal;
- 288 decisões de storage + 1 julgamento final = 289 receipts;
- TCAP:
  `d869147fff02124069d64a223da5c6a5c4818c80276f8af1d58522313fe29a94`.

A auditoria causal ocupa 747.698 bytes. Archive + auditoria somam 1.074.301
bytes, 5,493 vezes o FFV1. Esse custo não é necessário para playback, mas é
publicado separadamente; não pode ser escondido em uma alegação de custo frio
integral.

## Por que o temporal perdeu

Sobre exatamente os 252 tiles com referência:

- seleção espacial efetiva: 280.489 bytes;
- `TEMPORAL_SUB_ZLIB`: 375.957 bytes, 34,0363% maior;
- `TEMPORAL_XOR_ZLIB`: 412.207 bytes, 46,9601% maior.

O preditor usa o tile na mesma posição do quadro anterior. Movimento de câmera,
movimento de objetos, deformação, oclusão e mudança de iluminação deslocam a
informação; o XOR/subtração homólogos transformam isso em residual denso.
Paeth continua encontrando correlação espacial dentro do quadro e vence.

Portanto, a causa observada não é falha de round-trip, container ou política T.
É insuficiência do modelo de movimento.

## Controle sintético

Em um caso explicitamente sintético, com base espacialmente imprevisível e
pequenas mudanças entre quadros:

- zlib global: 110.633 bytes;
- CASV/0.6: 37.620 bytes;
- 8 tiles temporais selecionados;
- mutação somente T, proibindo temporal: 111.076 bytes e `REJECT`;
- ruído independente: `REJECT`;
- 9/9 gates passaram.

Isso prova execução e causalidade do mecanismo, não eficácia em vídeo natural.

## Evidência

- sintética final:
  `C:\CasuloLab\campaigns\2026-09-10-casv-temporal-v06-synthetic-attempt2`;
- real final:
  `C:\CasuloLab\campaigns\2026-09-10-casv-temporal-v06-real-clip8-attempt2`;
- manifest sintético:
  `89cce1506fbaed0d5ae43803f041b9634db87a6c4c21ba1ff4cc0732054d155c`;
- sums sintético:
  `bfa18087cc541cec01a233734dc4715b693cb96cf357735b228b5b3189212fa0`;
- manifest real:
  `b2554fb7a26458811fa527716b9bb34c33c31a3c1f45ef59e75c06e5365d85ed`;
- sums real:
  `cc5f873425526e87b656a6f7422cc5a6dfb86980a45422f6a17ee1ddafbd54c7`.

Tentativas anteriores permanecem preservadas; somente `attempt2` corresponde
ao código formatado e à classificação competitiva explícita desta entrega.

Validação final: 93 testes CASV passaram, incluindo 24 casos temporal/import;
os 3 testes do executor Productive T batch, `compileall`, Ruff, Cargo fmt,
build release e Cargo test também passaram. As regressões específicas congelam
a recusa de fonte com SHA-256 divergente e os seis limites da classificação
competitiva antes de qualquer nova campanha.

## Próximo ataque inevitável

O próximo gate não deve adicionar outro compressor genérico. Deve criar um
preditor temporal com compensação de movimento inteira e reversível:

1. busca bounded de vetor `(dx, dy)` por tile;
2. custo do vetor incluído no bitstream;
3. referência confinada ao quadro anterior e ao domínio válido;
4. keyframe/fallback exatos;
5. T escolhendo entre espacial, homólogo e movimento;
6. três clips naturais pré-congelados, não usados para desenhar o algoritmo;
7. vitória exigida contra o menor de zstd, FFV1 e x265 lossless.

Se os vetores + residual continuarem maiores que FFV1, o caminho deve ser
rejeitado e a próxima hipótese passa a ser gramática visual/segmentação
semântica — nunca ajuste retrospectivo do gate.
