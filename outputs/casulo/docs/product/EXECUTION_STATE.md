# Estado de execução do produto

## 2026-09-17 — CASULO FAMILY RP0.1 Day 1

Estado: `FAMILY_RP01_DAY1_MOCK_PASS_DAY2_MODEL_PENDING`.

- foi criado um slice stdlib-only em `src/casulo/family` com contratos,
  gateway HTTP/SSE loopback, fila SQLite persistente, supervisor, memória mock
  isolada por usuário e auditoria JSONL encadeada por hash;
- o engine determinístico rotula a resposta como `[MOCK LOCAL]`; nenhuma
  inferência de modelo é alegada;
- schemas versionados congelam os payloads de pergunta e evento;
- o smoke atravessou cliente -> gateway -> scheduler -> supervisor -> resposta,
  confirmou memória mock e reportou listener `127.0.0.1`;
- os testes cobrem recusa de bind não-loopback, contexto ausente, isolamento,
  serialização de trabalho pesado, cancelamento idempotente e unicidade do
  evento terminal;
- validação focal: `4 passed` em 2,15 s; regressão ampla: `773 passed,
  1 skipped, 42 subtests passed` em 125,85 s; compileall e parse dos schemas
  passaram;
- evidência: `CASULO_FAMILY_RP01_DAY1_MOCK_SLICE.md` e
  `evidence/family-rp01/day1-mock-slice.json`.

Próximo gate: Dia 2 — runtime/modelo local 7–9B quantizado, somente loopback,
com aquisição oficial, hashes/licença e benchmark CPU/aceleração sem romper o
piso permanente de 30 GB livres.

## 2026-09-17 — CASULO FAMILY RP0.1 Day 0

Estado: `FAMILY_RP01_DAY0_ARCHAEOLOGY_PASS_DAY1_MOCK_PENDING`.

- o snapshot bruto permanece em
  `100885dc009aed077a3ec2ac7d82a8b8de6b30a7`, tree
  `6ce76021d0991097951168c423137977d8cc9e78` e tag
  `casulo-stage0-raw-2026-09-17`;
- o remote `alemofer-hash/Casulo` foi verificado como privado antes do avanço
  de `main`; a tag remota continua ancorada no commit bruto;
- a política universal de bootstrap foi versionada em `AGENTS.md` no commit
  `d9aca5461af31fcb24000f2872825c52c5b80e64`;
- a branch de integração `rp0.1-family` foi criada sem reorganizar o material
  histórico;
- o baseline vermelho foi congelado, cinco falhas de Windows Script Host foram
  classificadas como sandbox e três oráculos textuais NP11 como testes
  obsoletos;
- após atualizar somente as seis expectativas NP11, o gate curto completo
  passou: `769 passed, 1 skipped, 42 subtests passed` em 200,58 s;
- `outputs/casulo` foi escolhido como raiz de código, com integração nova em
  `src/casulo/family`; Cloud permanece `RELEASE_LOCKED`, a Tauri owner UI não
  é apresentada como PWA e Native/CASV não entram no caminho crítico;
- mapa, decisão arquitetural e baseline estão em
  `CASULO_FAMILY_RP01_DAY0_ARCHAEOLOGY.md`,
  `CASULO_FAMILY_RP01_CANONICAL_ARCHITECTURE.md` e
  `evidence/family-rp01/day0-baseline.json`.

Próximo gate: implementar o slice mock loopback do Dia 1 e provar
cliente -> gateway -> supervisor -> resposta, com fila, correlação e auditoria.

## 2026-09-11 — CV1.8 movimento inteiro CASV/0.7

Estado: `MOTION_ENGINEERING_PASS_COMPETITIVE_BRANCH_REJECTED`.

- compensação de movimento inteira, bounded e reversível foi implementada com
  `(dx,dy)` assinado dentro do payload e custo integral entregue a T;
- decoder independente stdlib-only valida raio, geometria, keyframes, hashes,
  cadeia de receipts e reconstrói a mídia canônica byte a byte;
- probe sintético selecionou 12 tiles motion e produziu 9.968 bytes; mutação
  exclusivamente T selecionou zero, produziu 18.980 bytes e mudou TCAP/trace;
- três holdouts naturais pré-registrados produziram razões contra FFV1 de
  1,712257, 1,739936 e 1,783692; média geométrica 1,745048 e zero vitórias;
- em cada holdout, 13.104 vetores foram examinados, mas nenhum venceu os
  preditores espaciais;
- o gate de engenharia passou e o competitivo falhou; estado congelado:
  `REJECT_MOTION_BRANCH_AND_ADVANCE_TO_CAUSAL_VISUAL_GRAMMAR`;
- campanha append-only:
  `C:\CasuloLab\campaigns\2026-09-11-casv-motion-v07-natural-holdouts-attempt1`;
- manifest:
  `dfccc684e60ae8e7af50677b6e73d2f646b29d44d86ea6fef8058166f9de26ca`;
  SHA256SUMS:
  `5af77284c32834852aec08885be292b0cdb4d9b82abc9c9f4f7744441423c0bd`;
- 393/393 entradas e hashes conferiram; 103 testes CASV, sete testes focais,
  Ruff e compileall passaram;
- nenhum encode 8K integral, áudio, benchmark energético, Cloud, USB,
  owner/public ou release foi iniciado ou alterado.

Leitura honesta: o mecanismo de movimento é real, causal e exato, mas sua
hipótese competitiva foi falsificada nos holdouts. O residual, não o índice,
continua dominante.

Próximo passo exato: encerrar o ramo de predição translacional local e
pré-registrar CV2, uma gramática visual causal multiescala com regiões, bordas,
planos, câmera, iluminação e residual exato, confrontada em holdouts naturais
novos contra o menor codec lossless maduro.

## 2026-09-10 — CV1.7 predição temporal CASV/0.6

Estado: `CV1_7_TEMPORAL_PATH_PASS_NATURAL_SIGNAL_REJECTED`.

- CASV/0.6 acrescenta `TEMPORAL_XOR_ZLIB` e `TEMPORAL_SUB_ZLIB` com referência
  confinada ao tile homólogo do quadro anterior, keyframes explícitos e
  reconstrução byte-exact;
- encoder e decoder mantêm somente uma faixa ativa em memória e o quadro
  anterior em spool temporário anônimo; o decoder independente usa apenas a
  biblioteca padrão e recusa referências temporais em keyframes;
- T escolhe cada modo antes do commit e julga o archive reconstruído contra
  zlib global; uma mutação exclusivamente T que proíbe temporal mudou source,
  TCAP, trace, receipts e resultado no controle sintético;
- no controle sintético, CASV/0.6 produziu 37.620 bytes contra 110.633 de zlib,
  selecionou oito tiles temporais e passou 9/9 gates; a mutação espacial
  produziu 111.076 bytes e foi rejeitada;
- na evidência natural real de oito quadros 256×144 `YUV444P10LE`, 252 tiles
  admitiam referência temporal, mas T selecionou zero: o custo espacial foi
  280.489 bytes, contra 375.957 para SUB e 412.207 para XOR;
- o archive natural CASV/0.6 tem 326.603 bytes e SHA-256
  `a09ef34ff4b8fa03b2c5fa174668d044b4e85a3e41af6bc452392deded75d9a3`;
  a mídia canônica tem 1.769.472 bytes e SHA-256
  `afb40c79c9a6d3bb2b6a9a73800da4eb9a9a183ed3761eac2ded71d4d67b98`;
- CASV venceu zlib por 10,1626%, porém perdeu por 10,5349% para zstd, 22,2454%
  para x265 lossless e 66,9971% para FFV1; a razão CASV/FFV1 foi 1,669971;
- todos os quatro baselines foram reconstruídos aos mesmos bytes e SHA-256;
  288 decisões de storage e um juízo T produziram 289 receipts;
- validação fechada: 93 testes CASV, incluindo 24 testes temporal/import, e 3
  testes Productive T batch passaram; o caminho natural é classificado
  `PASS_ENGINEERING_NEGATIVE_VS_MATURE_BASELINE`;
- evidência final append-only:
  `C:\CasuloLab\campaigns\2026-09-10-casv-temporal-v06-synthetic-attempt2` e
  `C:\CasuloLab\campaigns\2026-09-10-casv-temporal-v06-real-clip8-attempt2`;
- manifestos raiz: sintético
  `89cce1506fbaed0d5ae43803f041b9634db87a6c4c21ba1ff4cc0732054d155c`
  e real
  `b2554fb7a26458811fa527716b9bb34c33c31a3c1f45ef59e75c06e5365d85ed`;
- espaço livre ao fechar o gate: 66,96 GiB na unidade C:;
- nenhum encode integral 8K, áudio, benchmark energético, Cloud, USB,
  owner/public ou release foi iniciado ou alterado.

Leitura honesta: a arquitetura temporal, a causalidade T e o round-trip
passaram; a hipótese de referência homóloga simples foi falsificada neste clip
natural e CASV/0.6 não é competitivo com codecs lossless maduros.

Próximo passo exato: implementar compensação de movimento inteira, bounded e
reversível, incluir o custo do vetor no bitstream e testar em três clips
naturais pré-congelados contra o menor de zstd, FFV1 e x265 lossless. Se o gate
continuar negativo, encerrar esse ramo e migrar para gramática visual causal.

## 2026-09-10 — CV1.6 compact binary index CASV/0.5

Estado: `CV1_6_COMPACT_INDEX_PASS_TEMPORAL_PREDICTION_PENDING`.

- CASV/0.5 substitui o manifesto JSON embutido por header, records, tabela de
  tiles e footer binários; overhead determinístico
  `156 + 44×records + 5×tiles`;
- T continua selecionando cada tile antes do commit e agora julga o archive
  completo contra zlib global antes do rename/publicação;
- vereditos são `ACCEPT_BEATS_REFERENCE`, `ACCEPT_RAW_ONLY` e `REJECT`; um
  candidato rejeitado é preservado apenas em evidência;
- decoder independente stdlib-only, player, CLI, importação FFmpeg direta e
  migração verificada 0.4→0.5 foram implementados e testados;
- no stream real derivado selado de dois quadros 256×144 YUV444P10LE:
  raw 442.368, zlib 94.890, payload 83.650, record stream 84.802 e archive
  final 84.958 bytes;
- o arquivo completo venceu zlib por 9.932 bytes / 10,4669% e ficou 17,1117%
  menor que o CASV/0.4 sobre os mesmos pixels;
- SHA-256 canônico
  `eb1c094a58e0c79aa7a75075c31638cd20b884a7526b0786bf16342730bc3aa8`;
  archive
  `74ee0b4e85869b8f4ead977bfa0f89e6d42f3d44059c463fa661ce7684fc5368`;
- 72 decisões de storage + um juízo final produziram 73 receipts; TCAP
  `4b1bfb803e58749502a94408d2c9608b9c46ebf4ee1d493216eb7fd4c2914b0c`;
- artifacts forenses externos somam 191.958 bytes; archive + auditoria são
  276.916 bytes e perdem para zlib por 191,8284%, custo preservado e separado
  do bitstream necessário ao playback;
- o probe sintético inicial que favorecia zlib ficou preservado como FAIL; o
  probe corrigido de rampa espacial, mutação T e ruído passou 7/7;
- validação: 78 testes CASV, 19 focais compact/import, 3 Productive T batch,
  cargo test, ruff focal e compileall PASS;
- evidência final append-only:
  `C:\CasuloLab\campaigns\2026-09-10-casv-compact-v05-synthetic-attempt5` e
  `C:\CasuloLab\campaigns\2026-09-10-casv-compact-v05-real-crop-repack-attempt4`;
- manifests conferidos em 147/147 e 48/48 entradas; sete hashes da
  implementação coincidiram com o worktree no selo;
- espaço livre ao encerrar o gate: 67,03 GiB na unidade C:;
- nenhum encode integral 8K, áudio, benchmark energético, Cloud, USB,
  owner/public ou release foi iniciado ou alterado.

Leitura honesta: o gate de índice compacto passou e o archive completo venceu
zlib neste único recorte real. Não há generalização para vídeo natural, HEVC ou
codecs lossless maduros, nem prova de custo computacional competitivo.

Próximo passo exato: CASV/0.6 com delta temporal por tiles homólogos,
keyframes/fallback exatos e clips naturais pré-congelados contra zlib, zstd,
FFV1 e x265 lossless; somente depois ampliar resolução e duração.

## 2026-09-10 — CV1.5 spatial tiling bounded CASV/0.4

Estado: `CV1_5_SPATIAL_TILING_PASS_COMPACT_INDEX_PENDING`.

- implementado layout frame/plane/strip/tile para RGB8 e `YUV444P10LE`, sem
  alocar um quadro inteiro;
- aritmética 8K validada: um quadro YUV10 de 212.336.640 bytes vira 102 faixas
  e 1.632 tiles; maior faixa 2.097.152 bytes; encode 8K integral não executado;
- T escolhe antes do commit, por tile, entre DC/XOR+zlib, Paeth+zlib, zlib e
  raw; 72 decisões reais do crop foram amortizadas em 18 processos Rust, sem
  colapsar receipts ou hash chain;
- runtime T recebeu modo batch geral, com uma máquina semântica nova por item,
  validação de cardinalidade/ordem e compatibilidade com a invocação unitária;
- decoder independente stdlib-only valida footer, manifesto, offsets, hashes,
  tabelas, limites e recompõe uma faixa por vez;
- probe sintético corrigido: 7/7 gates PASS, policy mutation somente T alterou
  storage, ruído expandiu e recebeu `REJECT`;
- crop natural real de dois quadros: 442.368 bytes canônicos, 83.650 bytes de
  payload de tiles, 86.170 bytes no record stream e 94.890 bytes em zlib
  global; sinal espacial de 11,845% no payload e 9,190% no record stream;
- o manifesto JSON de 16.271 bytes apagou o sinal: archive final 102.497 bytes,
  ou 7.607 bytes / 8,017% maior que zlib global;
- SHA-256 canônico
  `eb1c094a58e0c79aa7a75075c31638cd20b884a7526b0786bf16342730bc3aa8`;
  archive
  `9b078c113153f43cba2c7d4d73c848e23c995cce1cd81ce1efba83ca05c64945`;
- a métrica ambígua que chamava record stream de payload recebeu regressão
  red/green e foi dividida em payload, record stream e archive; evidência antiga
  permanece intacta e uma recomposição derivada registra a correção;
- validação: 56 testes CASV/T PASS, cargo test/build release PASS, ruff,
  rustfmt e compileall PASS;
- evidência append-only:
  `C:\CasuloLab\campaigns\2026-09-10-casv-tiled-v04-synthetic-attempt2` e
  `C:\CasuloLab\campaigns\2026-09-10-casv-tiled-v04-real-crop-attempt2`;
- tentativa `attempt1` rejeitada antes do workload por hash esperado digitado
  incorretamente foi preservada com receipt; nenhum archive foi publicado;
- nenhum vídeo integral, áudio, benchmark energético, Cloud, USB, owner/public
  ou release foi iniciado ou alterado.

Leitura honesta: spatial tiling e autoridade causal passaram; o transform
espacial encontrou economia real dentro do crop, mas o formato 0.4 perdeu essa
economia no índice/manifesto. Não há prova de compressão natural como classe,
8K integral ou vantagem contra codec maduro.

Próximo passo exato: criar CASV/0.5 append-only com índice binário compacto,
manter reconstrução independente e fazer T julgar o custo total; depois
introduzir delta temporal por tile antes de ampliar o probe natural.

## 2026-09-10 — CV1.4 programa causal segmentado CASV/0.3

Estado: `CV1_4_CAUSAL_PROGRAM_PASS_SPATIAL_TILING_PENDING`.

- implementado CASV/0.3 frame-aligned com payloads
  `base + dinâmica + residual XOR`, zlib e raw concorrendo por segmento;
- T escolhe o candidato observado antes do commit; mutação exclusivamente T
  alterou três segmentos de `GENERATIVE_EXACT` para `CANONICAL_RAW`, com
  TCAP/receipts diferentes e SHA-256 reconstruído igual;
- renderer e decoder independente suportam RGB8 packed e `YUV444P10LE`
  planar nativamente;
- decoder 0.3 não importa encoder, IR, proposer ou T, valida limites/hashes e
  sustenta verify, unpack, extração seletiva e player por pipe;
- adapter direto preserva ausência de raw intermediário, backpressure, timeout,
  stderr bounded, tamanho/EOF exatos e exit code zero antes de publicação;
- probe sintético: RGB programa 450 contra zlib 534 bytes; YUV10 programa 224
  contra zlib 350; ruído expandiu e recebeu `REJECT`; 7/7 gates PASS;
- recorte natural de dois quadros: programa 93.569 contra zlib 94.890 bytes,
  ganho de payload 1,392%; archive 99.130 bytes, ainda 645 bytes maior que o
  melhor archive histórico por custo de proveniência;
- recorte natural de oito quadros: programa 357.828 contra zlib 363.549 bytes,
  ganho de payload 1,574%; archive 363.402 bytes e round-trip exato;
- o proposer encontrou zero tracks naturais, previu exatamente menos de 0,8%
  dos pixels e o FFmpeg levou 126,002 s para oito quadros: sinal de compressão
  pequeno, explicação semântica fraca e custo de encode negativo;
- um quadro 8K YUV10 tem 212.336.640 bytes e excede o segmento de 64 MiB; o
  encoder recusa e exige spatial tiling, portanto nenhum 8K integral ocorreu;
- validação: 17 testes novos coletados, regressão de compressão `90 passed`,
  pipeline T `61 passed, 42 subtests passed`, ruff/py_compile PASS;
- evidência append-only:
  `C:\CasuloLab\campaigns\2026-09-10-casv-program-v03-synthetic-attempt1`,
  `C:\CasuloLab\campaigns\2026-09-10-casv-program-v03-real-crop-attempt1` e
  `C:\CasuloLab\campaigns\2026-09-10-casv-program-v03-real-clip8-attempt1`;
- nenhum vídeo integral, áudio, benchmark energético, Cloud, USB, owner/public
  ou release foi iniciado ou alterado.

Leitura honesta: o mecanismo causal agora existe e venceu zlib no payload dos
dois recortes naturais medidos. Isso não demonstra compressão de vídeo natural
como classe nem vantagem contra codec maduro. O residual continua dominante e
o custo computacional ainda é impraticável.

Próximo passo exato: implementar spatial tiling bounded, proposer linear e
preditores reversíveis por tile/plano, mantendo decisão T e decoder independente;
então executar clips naturais curtos pré-congelados contra zlib, zstd, FFV1 e
x265 lossless. Áudio somente em versão audiovisual nova.

## 2026-09-10 — CV1.3 importação FFmpeg por pipe direto

Estado: `CV1_3_DIRECT_FFMPEG_PIPE_PASS_AUDIO_CONTAINER_PENDING`.

- implementado `casv-stream-import`: FFmpeg stdout alimenta o encoder
  CASV/0.2 diretamente, sem materializar raw em disco;
- o plano valida fonte, SHA-256, probe, pixel format, crop, frames e limite de
  bytes antes de iniciar o produtor;
- leitura tolera fragmentação do pipe, mas exige comprimento exato e EOF;
  timeout, stream curto/longo e exit code não zero impedem o rename atômico;
- stderr é drenado concorrentemente com memória limitada; manifesto registra
  versões, hashes, argumentos redigidos, timestamps e hashes do código;
- contrato PCM canônico implementado e testado; CASV/0.2 permanece vídeo-only
  e não faz claim audiovisual;
- probe real: fonte HEVC 8192x4320 de 18.381.885.157 bytes, crop 256x144 por
  dois quadros, `YUV444P10LE`, 442.368 bytes canônicos;
- SHA-256 canônico:
  `eb1c094a58e0c79aa7a75075c31638cd20b884a7526b0786bf16342730bc3aa8`;
- archive: 102.753 bytes, sete segmentos zlib, SHA-256
  `e7497d3aa0c58b9f19e938997c001991f9031be8581348c95fc93e3a717c332f`;
- redução de 76,772054036% somente contra raw canônico; incluindo 49.560 bytes
  de autoridade externa, redução de 65,568712023%; nenhuma comparação com
  HEVC é autorizada;
- decoder independente, CLI inspect/verify e ffplay incremental real: PASS;
- validação: 8 testes do adapter, 14 do contrato de áudio, 59 de compressão e
  163 integrados + 42 subtests PASS; ruff/compileall PASS; manifesto 27/27;
- evidência append-only:
  `C:\CasuloLab\campaigns\2026-09-10-casv-8k-direct-pipe-attempt1`;
- nenhum vídeo integral, áudio, Cloud, USB ou benchmark energético foi
  iniciado.

Leitura honesta: eliminamos o arquivo raw intermediário e validamos a cadeia
direta em dados reais. O ganho de compressão natural continua não demonstrado:
CASV/0.2 usou somente zlib, processou um recorte de dois quadros e ficou maior
que o archive bounded anterior devido à segmentação/proveniência.

Próximo passo exato: segmentar `base + dinâmica + residual`, implementar
renderer nativo de 10 bits e executar clips naturais pequenos contra o source
e baselines maduros. Áudio entra somente em uma nova versão do container.

## 2026-09-10 — CV1.2 container CASV segmentado

Estado: `CV1_2_STREAM_CONTAINER_PASS_FFMPEG_STREAM_AND_AUDIO_PENDING`.

- implementado CASV/0.2 com escrita forward-only, manifesto no footer, 1 a
  65.536 segmentos e limites fail-closed;
- decoder independente verifica e entrega um segmento por vez; buffers
  explícitos são reportados sem fingir medição de RSS;
- extração seletiva lê somente ranges tocados e declara que não verificou o
  restante do payload;
- `casv-play` fez verificação integral e depois reprodução incremental real por
  `ffplay pipe:0`, sem mídia temporária;
- T recebeu índice e hash do bloco e emitiu um receipt distinto antes de cada
  commit; julgamento integral permaneceu pós-decode;
- probe sintético: 110.592 -> 68.344 bytes, 27 segmentos (13 raw, 14 zlib),
  round-trip e range exatos, corrupção recusada;
- archive SHA-256:
  `b188660a185412acf7caaa1306672465d632fba53edd67da79cac24285c0c22f`;
- TCAP:
  `8fdcb3fb294a4563efb639327dda9e8b2dba33519211f70a15ace161108f91e0`;
- validação: 18 testes CASV e 92 integrados PASS; ruff focal PASS; CLI
  inspect/verify exit 0; manifesto 52/52; ffplay real PASS;
- evidência:
  `C:\CasuloLab\campaigns\2026-09-10-casv-stream-v02-probe-attempt4`;
- nenhum workload longo, vídeo 8K integral, Cloud, USB ou benchmark energético
  foi iniciado.

Leitura honesta: infraestrutura streaming avançou; compressão natural não. O
0.2 atual escolhe somente raw/zlib. A redução de 38,20% contra raw sintético não
pode ser comparada ao HEVC.

Próximo passo exato: ligar FFmpeg stdout ao encoder segmentado sem arquivo raw
intermediário, adicionar contrato de áudio e segmentar a gramática
`base + dinâmica + residual`; então medir clips naturais pequenos.

## 2026-09-10 — CV1.1 precisão nativa e player por pipe

Estado: `CV1_NATIVE_SAMPLE_AND_PIPE_PLAYER_PASS_STREAMING_PENDING`.

- `CanonicalVideoSpec` e o decoder independente agora aceitam RGB8 e
  `YUV444P10LE`, com contabilidade de 3 ou 6 bytes por pixel;
- o importer possui rota explícita
  `EXACT_FFMPEG_DECODED_NATIVE_SAMPLE_STREAM`; formatos não suportados falham
  fechados em vez de sofrer conversão silenciosa;
- o renderer retangular continua somente RGB8. Para 10 bits, o candidato
  generativo é declarado indisponível e T escolhe causalmente zlib ou raw;
- o player envia o segmento verificado por stdin ao ffplay, sem mídia
  temporária. O decoder ainda é bounded/in-memory, não streaming incremental;
- probe real: mesma fonte HEVC 8192x4320 `yuv444p10le`, crop 256x144 por 2
  frames, 442.368 bytes canônicos;
- SHA-256 canônico:
  `eb1c094a58e0c79aa7a75075c31638cd20b884a7526b0786bf16342730bc3aa8`;
- zlib canônico: 94.890 bytes; raw: 442.368 bytes; generativo: indisponível;
- archive: 98.485 bytes; redução de 77,736861617% somente contra raw canônico;
- SHA-256 do archive:
  `63b7b8bba37084f871c693ae9cc3d965cb53eaf60b616f244b4145ee8b27c5bf`;
- T selecionou `CANONICAL_ZLIB`; TCAP:
  `05f5fb569fe3f1f393015e3dabaa5c4af8ab2e0ed33d664ec4192b6280f7b865`;
- decoder independente e player `YUV444P10LE`: PASS;
- evidência corrigida: 21/21 entradas revalidadas;
- validação: 11 testes CASV e 85 testes integrados PASS; `ruff` PASS;
- tentativa anterior de 10 bits preservada como pré-correção de um rótulo
  `kind`; nenhuma evidência foi sobrescrita.

Evidência:
`C:\CasuloLab\campaigns\2026-09-10-casv-8k-native10-import-attempt2`.

Limite: isso não mede tamanho contra o HEVC, não executa a fonte inteira, não
usa gramática generativa em 10 bits e não prova compressão de vídeo natural.

Próximo passo exato: container segmentado append-only, decoder incremental,
índice autenticado de seek e áudio canônico. Depois, ampliar a gramática visual
para que a explicação causal reduza o residual em clips naturais.

## 2026-09-10 — CV1 importador 8K bounded e player de referência

Estado:
`CV1_BOUNDED_8K_IMPORT_AND_REFERENCE_PLAYER_PASS_STREAMING_PENDING`.

Implementado:

- `casv-import` usa ffprobe/FFmpeg por argv, `shell=False`, valida SHA-256 da
  fonte, limita quadros e memória e nunca embute MP4/HEVC no `.casv`;
- proveniência agora distingue `EXACT_AFTER_RGB8_CANONICALIZATION` de
  identidade dos samples nativos;
- `casv-play` valida por decoder independente, abre a mídia pelo ffplay e
  remove o RGB temporário; perfil declarado
  `REFERENCE_TEMPFILE_NOT_NATIVE_STREAMING`;
- o manifesto CASV registra origem, codec, pixel format, dimensões, frame rate,
  versões e hashes de FFmpeg/ffprobe;
- testes cobrem comandos sem shell, fonte ausente, importação real curta,
  ausência do bitstream no archive e execução do player.

Execução real bounded sobre a fonte 8K preservada:

- fonte: 18.381.885.157 bytes, HEVC 8192x4320, `yuv444p10le`,
  60000/1001 fps;
- SHA-256 da fonte:
  `68011a473a3c3f963dfe716620991eb92d87473e9a7204ae323a1dceb0502d24`;
- derivação: crop 256x144, 2 frames, 221.184 bytes RGB8;
- SHA-256 canônico:
  `ac2ffd7f7b16116e354e87f74abfd9ac635c600bab064c4d6feccf0fb380d2d7`;
- archive CASV: 68.031 bytes; SHA-256:
  `40c91d35d58852c0930db4f98d69dc517277407dcc39e0e87c1626910bd9b604`;
- candidates: generativo 65.654 bytes, zlib canônico 64.852 bytes, raw
  221.184 bytes; T escolheu `CANONICAL_ZLIB` antes do commit;
- 21 tracks propostos explicaram somente 3.379/73.728 pixels, cerca de 4,58%;
- round-trip independente do RGB8: PASS;
- player de referência sobre `.casv` real: PASS;
- manifesto de evidência: 21/21 entradas verificadas;
- testes: 10 CASV focalizados PASS; regressão integrada 84 PASS; `ruff` PASS.

Leitura científica: a infraestrutura de formato/importação/reconstrução está
positiva, mas o compressor causal natural ainda está negativo. O candidato
generativo perdeu 802 bytes para zlib nesse recorte. A redução de 69,24% contra
RGB8 cru não pode ser comparada ao MP4 comprimido e não prova compressão 8K.
Além disso, converter `yuv444p10le` para RGB8 não preserva a precisão nativa.

Evidência append-only:
`C:\CasuloLab\campaigns\2026-09-10-casv-8k-import-plumbing-attempt1`.

Próximo passo exato: concluir CV1 com representação canônica que preserve
bit-depth/espaço de cor/chroma, segmentos streaming, índice de checkpoints e
player sem mídia temporária. Só então iniciar CV2 (layers, gradientes, alpha,
curvas, iluminação e texturas determinísticas) sobre clips naturais pequenos.

## 2026-09-10 — CV0 formato visual causal próprio executado

Estado: `CV0_CASV_NATIVE_FORMAT_BOUNDED_PROBE_PASS`.

- implementado envelope binário `.casv` próprio, com magic/version, manifesto
  canônico e seções contíguas hasheadas; não é ZIP, MP4 ou HEVC reempacotado;
- contrato atual é `EXACT_MEDIA`: sequência RGB8 reconstruída byte a byte; a
  identidade binária do source container é deliberadamente separada;
- implementada representação efetiva `base + dynamics XOR residual`: geometria
  e materiais, movimento linear e fechamento exato;
- renderer `casulo.rectilinear-rgb8/0.1` usa aritmética inteira, cor/brilho e
  bordas pixel-aligned; alpha, antialiasing, textura, áudio e luz espacial ainda
  não existem;
- decoder independente stdlib-only não importa encoder, IR, proposer,
  autoridade T nem runtime;
- T/2 escolhe antes do commit entre `GENERATIVE_EXACT`, `CANONICAL_ZLIB` e
  `CANONICAL_RAW`, e julga o custo integral depois do decode independente;
- mutação somente em T mudou TCAP e representação de generativa para raw,
  preservando o SHA-256 canônico;
- probe estruturado sintético: 96x54, 24 frames, 373.248 bytes RGB -> 2.591
  bytes CASV, redução de 99,305823474%, dois tracks e residual zero;
- artifacts de autoridade por encode somaram 31.801 bytes; CASV + esses
  artifacts ficou em 34.392 bytes. Runtime/decoder compartilhados não foram
  integralmente alocados, logo não é custo cold-system;
- controle de ruído: 373.248 -> 375.393 bytes; T escolheu raw e retornou
  `REJECT` em vez de alegar compressão;
- zlib direto do corpus estruturado ocupou apenas 829 bytes; portanto o probe
  prova formato/execução/causalidade, não superioridade sobre codecs;
- `ruff` PASS; 7 testes CASV PASS; regressão integrada 81 PASS; seis gates do
  probe PASS; `casv-verify` PASS nos braços estruturado e ruído;
- evidência append-only:
  `C:\CasuloLab\campaigns\2026-09-10-casv-native-format-probe-attempt1`;
- `.casv` SHA-256:
  `521334a68a926e17e2ef6258ea9875b24121891cd9fb32ba575abb321c267443`;
- `PROBE_MANIFEST.json` SHA-256:
  `7222426398c76120dbfd350098175bee64a286aec2ee72e564299b75dfac8b9d`;
- nenhum workload longo, vídeo 8K integral, rede, Cloud, owner/public/Native,
  USB ou campanha energética foi iniciado ou alterado.

Claims autorizados: CASV/0.1 é um formato visual próprio executado em probe
bounded; houve reconstrução RGB8 exata, causalidade T na seleção/julgamento e
rejeição honesta do controle incompressível.

Claims proibidos: compressão de vídeo natural/8K, inferência neural, áudio,
player final, vantagem sobre HEVC/zstd/7-Zip, compressão próxima de 100% de uma
fonte externa, economia de datacenter ou produto comercial pronto.

Próximo passo exato: `CV1_STREAMING_IMPORT_AND_PLAYER` — implementar importer
MP4 -> mídia canônica sem bitstream embutido, decoder/player streaming com
working set limitado, índice de seek e contrato de áudio; executar somente
probes naturais curtos antes de autorizar o 8K integral.

## 2026-09-10 — LC3.1 caminho causal HEVC GOP/NAL executado

Estado: `LC3_GOP_CAUSAL_PATH_SHORT_PROBE_PASS_COST_REJECTED`.

- a campanha longa continua interrompida; nenhum workload integral de 18,38 GB
  foi retomado;
- implementado mapa completo de 600 samples, 1.200 NAL units e três grupos GOP
  com leitura bounded de prefixos e headers;
- implementado corpus alinhado a samples, iniciado em IRAP, sem truncamento de
  access unit;
- implementada IR `casulo.hevc-gop-transform-ir/1.0` com partição byte a byte
  `base + dynamics + residual`;
- implementados `raw`, `zlib` e `xor-reference-prefix-zlib`, todos com inversa
  local validada; o XOR usa referência anterior da mesma classe;
- T/2 governa `plan`, `decide` e `judge` pelo frontend, análise semântica, IR,
  grafo, TCAP e runtime Rust;
- mutação somente em T mudou famílias, 9 -> 4 invocações, trabalho, transforms
  e identidade do archive, preservando o corpus reconstruído;
- decoder stdlib-only, sem importar encoder/transforms/autoridade/runtime,
  reconstruiu os dois braços exatamente;
- fonte real: 18.381.885.157 bytes, SHA-256
  `68011a473a3c3f963dfe716620991eb92d87473e9a7204ae323a1dceb0502d24`;
- probe: duas samples completas, 60.229.738 bytes, SHA-256
  `747498e7a5357860e78d5a49f8a1ee03cd072acbb1a9bd81a2f6dc84505a4c59`;
- o candidate XOR foi executado, mas expandiu 334 bytes; zlib economizou 58.949
  bytes no segundo corpo VCL;
- payloads reduziram 0,097913%, mas o archive completo expandiu 4.016 bytes,
  `+0,0066678025%`; T retornou `REJECT`;
- arquivo padrão: 60.233.754 bytes; force raw: 60.283.111 bytes;
- lint PASS; 19 testes focados PASS; 74 testes integrados PASS; verificadores
  independentes PASS; manifesto 112/112 válido;
- evidência final:
  `C:\CasuloLab\campaigns\2026-09-10-hevc-gop-causal-probe-attempt4`;
- MANIFEST SHA-256:
  `904795b0c09b67b34b8c9a6c3d92477076eb7111002d02a90b9d48baf90f460f`;
- espaço livre observado: aproximadamente 73,97 GiB;
- nenhum processo longo permaneceu ativo; owner/public/Cloud/Native, rede, USB
  e campanhas energéticas não foram alterados.

Claims autorizados: caminho GOP/NAL v1 executado; partição exata, reconstrução
independente, autoridade causal T e rejeição honesta do custo passaram. Claims
proibidos: compressão do vídeo integral ou de GOP completo, compressão próxima
de 100%, domínio de pixels, superioridade sobre HEVC ou produto comercial.

Próximo passo exato: implementar processamento streaming com working set
limitado e representação de parameter sets, slice headers e relações de
referência; repetir probes bounded antes de autorizar um GOP completo.

## 2026-09-09 — LC3 caminho estrutural executado em probe curto

Estado: `LC3_STRUCTURAL_PATH_IMPLEMENTED_SHORT_PROBE_PASS`.

- a campanha longa anterior continua interrompida e não foi retomada;
- implementada IR `casulo.reversible-transform-ir/1.0` com cobertura byte a
  byte e partições explícitas `base + dynamics + residual`;
- implementado parser ISO BMFF/MP4 seguro, `hvcC`, `stsz`, `stsc`, `stco/co64`
  e inspeção bounded de headers NAL HEVC;
- a fonte real foi identificada como `hev1`, 600 amostras, 33 boxes; 64 headers
  de amostra foram inspecionados e a entropia amostral do `mdat` foi
  7,947413994 bits/byte;
- implementados CDC determinístico e transforms `raw`, `zlib`,
  `delta8-zlib`, `xor-prev-zlib` e `shuffle4-zlib`, todas com inversa local;
- T planeja candidates e seleciona payload antes da publicação pelo pipeline
  T/2 completo e runtime Rust; 14 receipts cobrem sete segmentos;
- mutação somente da política T mudou source/IR/TCAP, primitives executadas
  (19 -> 7), bytes de candidates, transform trace e archive;
- decoder stdlib-only independente do encoder, transforms e runtime T
  reconstruiu os dois braços para o SHA-256 exato do probe;
- gate focal integrado: `68 passed`; subset estrutural: `13 passed`;
- evidência final:
  `C:\CasuloLab\campaigns\2026-09-09-structural-architecture-probe-attempt8`;
- probe: 4.204.386 bytes, SHA-256
  `8f3fe0bb427e04cae2004d53f7b1159f42b585e5f1b1525b4e75cc9440992b69`;
- payloads selecionados reduziram 0,290958%, mas o archive completo de
  4.280.913 bytes expandiu 1,820171%: `NEGATIVE_NET_EXPANSION`;
- `attempt3` preserva a falha descoberta quando sample offsets do `moov`
  integral foram aplicados ao `mdat` truncado; modo normal permanece estrito;
- MANIFEST final SHA-256:
  `4798362fb6610eda8c7a4f31c18084bdb28544f14f7fe1f4e6dc332b751e0056`;
- espaço livre observado após os probes: aproximadamente 70,24 GiB;
- owner/public/Cloud/Native não foram alterados; nenhuma API externa, USB,
  benchmark energético ou campanha longa foi executada.

Claims autorizados: arquitetura estrutural v1 executou; round-trip independente
e causalidade T passaram no probe derivado. Claims proibidos: ganho no vídeo
integral, compressão próxima de 100%, superioridade sobre codecs ou produto
comercial comprovado.

Próximo passo exato: implementar modelagem HEVC inter-frame/GOP com residual
integral e custo total, migrar primitives aprovadas para Rust/SIMD e passar
probes crescentes de 64 MiB, 256 MiB e 1 GiB antes de congelar uma nova LC4.

## 2026-09-09 — campanha 8K pausada para auditoria arquitetural

Estado: `LC4_GENERIC_BASELINE_INTERRUPTED_ARCHITECTURE_GAP_CONFIRMED`.

- proprietário solicitou a interrupção antes de aceitar qualquer resultado;
- runner Python PID 10280 e filho 7-Zip foram encerrados às
  `2026-09-09T21:48:03.1807963-03:00`; nenhum processo da campanha permaneceu;
- fonte, arquivos completos, receipts, dois fragmentos 7-Zip e logs foram
  preservados em
  `C:\CasuloLab\campaigns\2026-09-09-video8k-proof-v1-live-attempt3`;
- Casulo genérico e zstd possuem restaurações bit-exact registradas; 7-Zip não
  terminou; `report.json` está ausente e não há classificação final;
- auditoria confirmou que o caminho medido é LC1: chunks fixos, SHA-256,
  deduplicação idêntica e raw/zlib; não há perfil estrutural de vídeo, IR
  Frozen-to-Dynamics, autoridade T, codificação colunar ou runtime nativo;
- a campanha iniciou LC4 sem implementar LC3, portanto não mede a hipótese
  central pretendida para o Casulo;
- nenhum novo benchmark pode iniciar antes dos gates registrados em
  `docs/product/LOSSLESS_ARCHITECTURE_GAP_AUDIT_2026-09-09.md`;
- próximo passo exato: especificar a IR reversível e implementar o perfil
  estrutural de vídeo com probes curtos e verificador independente.

## 2026-09-09 — LC1 compressão sem perda e laboratório local

Estado: `LC1_LOSSLESS_CORE_AND_LAB_READY`.

- trilha ativa alterada pelo proprietário para duas provas reais de compressão:
  vídeo 8K e 100 milhões de registros;
- produto voice-first e pesquisa científica/energética anteriores congelados e
  preservados; owner/public/Cloud/Native não foram alterados por este slice;
- Steam/GTA e Unity removidos por autorização explícita, recuperando 139,295
  GiB; Casulo e Jaderson preservados;
- FFmpeg/ffprobe 9.0.1, zstd 1.5.7, 7-Zip 26.03, DuckDB 1.5.5 e aria2 1.37.0
  instalados e executáveis;
- módulo `casulo.compression` adiciona contêiner determinístico, chunks
  content-addressed, deduplicação, codecs conservadores, pack/verify/unpack,
  probe 8K e laboratório contra zstd/7-Zip;
- gate focal: `8 passed`; compileall PASS; doctor `ready=true`;
- smoke no README foi bit-exact nos três braços e é explicitamente inelegível
  como prova comercial; Casulo 8.266 bytes, zstd 7.004 bytes. O resultado
  mostra que o candidato atual ainda perde esse controle pequeno;
- nenhuma fonte 8K ou base de 100M registros foi chamada de testada;
- protocolo congelado antes dos resultados em
  `docs/product/LOSSLESS_PROOF_PROTOCOL_V1.md`;
- aquisição em andamento da fonte real `000_10sec_8K.mp4`, com tamanho remoto
  esperado de 18.381.885.157 bytes; fonte ainda não aceita até tamanho,
  SHA-256 e `ffprobe` locais passarem;
- Cloud continua `RELEASE_LOCKED`; guest network e USB/block devices continuam
  fora desta trilha; nenhuma alegação de compressão próxima de 100% autorizada;
- roadmap vinculante: `docs/product/CASULO_LOSSLESS_COMPRESSION_ROADMAP.md`;
- próximo passo exato: concluir LC2-A validando tamanho, SHA-256, resolução,
  duração e quadros da fonte 8K; então executar a primeira prova bit-exact sem
  alterar protocolo ou limiares.

## 2026-08-22 — preflight físico SanDisk interrompido com segurança

Estado físico: `BLOCKED_PHYSICAL_MEDIA_UNSTABLE`.

- SanDisk Cruzer Blade identificado como Disco 1 USB/GPT de 8.004.304.896
  bytes, não boot e não system;
- layout observado: ESP de 1 GiB e Linux root x86-64 de ~6,93 GB;
- o dispositivo desapareceu duas vezes antes da montagem da ESP;
- PnP: `Present=false`, `Problem=45`;
- System log: eventos disk 153 (I/O retry) e 51 (device I/O error);
- zero mount concluído, zero arquivo copiado e zero escrita física;
- a instalação foi bloqueada para não arriscar o Arch existente;
- evidência: `outputs/casulo/native-multiboot/2026-08-22-sandisk-preflight-attempt-1/`.

Próximo passo físico: outra porta USB; se 51/153 reaparecerem, outra mídia.
Próximo passo arquitetural: transporte dividido, pois a ESP de 1 GiB não
comporta o system pack atual de 2.497.390.010 bytes.

## 2026-08-22 — NP11 e coexistência UEFI não destrutiva

Estado: `NATIVE_UEFI_MULTIBOOT_COEXISTENCE_VALIDATED_PHYSICAL_INSTALL_PENDING`.

- o modelo owner completo foi incorporado como nona entrada content-addressed
  do system pack e passou a ser consumido do ramdisk UEFI, sem `fw_cfg`;
- a imagem NP11 de 2.524.932.608 bytes executou boot-to-creation em QEMU/WHPX,
  com 34 tokens, T compilado, simulação, aceitação e materialização `PASS`;
- o instalador coexistente adiciona somente arquivos novos, recusa colisões e
  congela a árvore EFI por hash antes da aplicação;
- integra systemd-boot por entrada nova, GRUB somente quando o consumo de
  `custom.cfg` é comprovado, rEFInd por namespace auto-descoberto e mantém
  Windows/GRUB não comprovado como `UEFI_FIRMWARE_ENTRY_REQUIRED`;
- rollback por receipt remove apenas arquivos Casulo ainda inalterados;
- regressão focal final: 24/24 PASS, incluindo GRUB não comprovado, aplicação
  pela CLI e rollback vinculado ao receipt;
- a matriz final append-only Windows/GRUB/systemd-boot/rEFInd preservou todos
  os bytes preexistentes e restaurou o hash exato após rollback;
- nenhuma imagem crua foi gravada e nenhum dispositivo físico foi escrito;
- inventário read-only final expôs somente o NVMe interno. Boot físico,
  Secure Boot e persistência física continuam não verificados;
- Cloud permanece `RELEASE_LOCKED`, rede guest OFF, USB/block-device writes
  proibidos neste gate e benchmark científico não iniciado.

Documentação e evidência:

- `docs/product/NATIVE_MULTIBOOT_ARCHITECTURE.md`;
- `release/INSTALL_CASULO_MULTIBOOT.md`;
- `outputs/casulo/native-multiboot/2026-08-22-np11-ramdisk-qemu-attempt-2.json`;
- `outputs/casulo/native-multiboot/2026-08-22-coexistence-validation-attempt-4/`.

Próximo passo exato: reconectar um pendrive que apareça como disco removível,
identificar e montar somente sua ESP, executar `inspect` e `plan`, revisar o
resultado e então solicitar confirmação literal vinculada ao hash. Não gravar a
imagem NP11 crua sobre mídia que já contenha outro sistema.

## Casulo Native boot-to-creation — 2026-08-22

- Estado técnico: `CASULO_NATIVE_BOOT_TO_CREATION_PROOF`;
- kernel Casulo iniciou por UEFI em QEMU/WHPX sem Linux no guest;
- Qwen3-4B Q4_K_M owner, SHA-256
  `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5`,
  produziu 34 tokens autorregressivos idênticos ao oráculo `llama.cpp`;
- 3/3 boots positivos e 1/1 cancelamento fail-closed passaram;
- política T julgou cada token, a criação e a aceitação; o programa T retornou
  18, passou simulação e foi materializado na cena Stark + Jobs;
- imagem final SHA-256
  `25193857a96d6c14328d92fb128d6e666a31478dee05cc8cca6a35252932a534`;
- NP9 foi superseded por errata causal: RoPE adjacente corrigido para Qwen3
  NeoX split-half, sem apagar evidência histórica;
- regressões Python e workspace Cargo/Native: PASS; pacote reproduzível,
  SBOM, hashes e assinatura de desenvolvimento são gerados pelo selador;
- regressão final: `593 passed, 2 skipped` em produto/T/QEMU, `10 passed` no
  foco de release, `19 passed` no runtime neural Rust e `9 passed` no renderer;
- pacote final com layout executável e dependências externas explicitadas
  (Python, QEMU/OVMF e modelo owner verificado):
  `release/CASULO_NATIVE_BOOT_TO_CREATION_PROOF_2026-08-22-attempt-4.zip`,
  SHA-256
  `368433243159ce28c4e54b39774792bdae39d8748d3b24786fb5dbd60dde863e`;
- `attempt-5.zip` reproduziu bit a bit o mesmo pacote e SHA-256;
- assinatura Ed25519 de desenvolvimento, manifest, SBOM, `SHA256SUMS`, ZIP
  extraído e launcher foram verificados; GGUF não está no pacote;
- handoff final:
  `outputs/casulo/native-boot-to-creation/2026-08-22-np10-final-attempt-4/handoff.json`;
- espaço livre final observado: `65,07 GiB`;
- prova deliberadamente bounded: prompt/greedy congelados, CPU, modelo inteiro
  residente, QEMU `fw_cfg`, tempo de minutos, sem voz/memória/prompt arbitrário;
- nenhuma alegação de desempenho, energia, compressão, GPU/TPU ou release
  comercial foi autorizada;
- Cloud `RELEASE_LOCKED`, guest network OFF, public sem privados, USB/block
  devices não tocados, nenhum benchmark científico iniciado;
- prova humana não foi executada em nome de Guilherme;
- detalhes: `docs/product/NATIVE_BOOT_TO_CREATION_PROOF.md` e
  `docs/product/NATIVE_24H_EXECUTION_STATE.md`.

## Stark + Jobs Tauri vertical slice (2026-08-20)

- Estado: `STARK_JOBS_TAURI_VERTICAL_SLICE_PASS`;
- objetivo: transformar o protótipo Figma sintético em uma primeira superfície
  Hosted executável e produzir o plano causal de promoção ao Casulo Native;
- app novo: `apps/casulo-owner-ui` com React 19.2.8, Vite 8.2.2 e Tauri 2;
- frontend é projeção sem autoridade; backend Rust acompanha somente JSONL
  confinado em `%LOCALAPPDATA%\Casulo\experience`;
- contrato wire preservado: `casulo.owner-ux-event/1.0`, SHA-256
  `4d209cce708d843ffef50ac606ba199151be39eb9ecfff9c2c9fae233d24bcb9`;
- scene contract novo: `casulo.stark-jobs-scene/1.0`, SHA-256
  `804ceb12b510f250cfd41a6e49185fe8db73f13c09a7f3288703368889435a8d`;
- tokens aparecem somente por `ASSISTANT_TOKEN`; jobs exigem receipt SHA-256;
  duplicação, ordem inválida, progresso fabricado e conclusão tardia após
  cancelamento são recusados;
- fixture realmente codificada pelo runtime Python atravessou o validator Rust;
- UI registra listeners antes de `start_bridge`, impedindo perda inicial;
- stream path inválido vira `CONFIGURATION_REJECTED`, sem traceback ao usuário;
- WebView capability: somente `core:event:allow-listen/unlisten`; zero plugin
  shell, fs, HTTP ou network; CSP e fontes são locais;
- modo sintético é manual, rotulado `não é runtime` e inelegível como evidência;
- gates: Node `6/6 PASS`, Rust `5/5 PASS`, contrato Python focal `20/20 PASS`,
  regressão produto `524 passed, 1 skipped`, compileall PASS;
- build frontend: JS `207,78 kB` (`65,98 kB gzip`); CSS `10,30 kB`;
- executável release: `8.718.848` bytes, SHA-256
  `3f3b867aa8a94c784ce48f2a9f0ebf2910b1ca98a8b75721a5024b915d9f3e35`;
- smoke de processo por 3 segundos: PASS;
- inspeção browser: 1280x720 e 1440x900 sem overflow, zero recurso remoto,
  zero log de console, drawer/ESC PASS e contrastes principais >= `7,24:1`;
- dependências: 29 pacotes npm locais e 428 crates no lock; nenhum pacote
  global, driver, modelo, voz ou fonte instalado; espaço livre `63,29 GiB`;
- plano Native: `docs/product/STARK_JOBS_NATIVE_PROMOTION_PLAN.md`; o SO recebe
  `ProductEvent -> SceneState -> renderer`, nunca DOM/React/WebView no kernel;
- owner/public/cloud/release e `os/` não foram alterados por este Sprint;
- Cloud `RELEASE_LOCKED`; guest network OFF; USB/block devices proibidos;
  nenhum benchmark científico ou energético iniciado;
- design, prazer e química: `PROVISIONAL_OWNER_REVIEW_REQUIRED`;
- limitações: entrada de turnos, launcher unificado, voz, installer, Rive e
  execução independente da árvore permanecem para CP4/CP6/CP7/CP8/CP12;
- próximo passo exato: implementar CP4 com serviço owner persistente, canal de
  entrada tipado e continuação semântica; depois estabilizar o scene schema e
  iniciar NUI0 da promoção Native.

## Creative Interlocution — primeiro vertical slice (2026-08-20)

- Estado: `CREATIVE_INTERLOCUTION_VERTICAL_SLICE_PASS`;
- foco: experiência local de invenção; pesquisa científica está
  `FROZEN_PRESERVED_NOT_DEFAULT` e nenhuma campanha nova foi iniciada;
- `:criar` passou de duas perguntas obrigatórias para uma única descrição livre;
- `CreativeIntentProjection` mantém o ledger técnico e sua proveniência em
  background, mostrando ao usuário somente o espelho e uma escolha humana
  material quando indispensável;
- escolha de API, framework, banco, arquitetura, algoritmo, servidor, modelo ou
  hardware no texto de uma pergunta é rejeitada antes de chegar ao usuário;
- hipóteses, rota neural, RequirementGraph e T continuam persistidos e
  auditáveis; simplificação visual não remove evidência;
- marcos técnicos do worker ganham texto cotidiano no fluxo principal, mas o
  evento mantém `engineering_summary` e o mesmo SHA-256 para auditoria;
- `:nome` cria identidade persistente e hash-evidente do Guia sem grant,
  privilégio ou instrução escondida;
- `GuidePresence` agora pede cenas e resultados reconhecíveis em vez de exigir
  que a pessoa formule finalidade/restrição em vocabulário de engenharia;
- conversa owner continua local por Qwen/llama.cpp, sem API externa;
- Cloud continua `RELEASE_LOCKED`; public/owner permanecem separados; rede
  guest, USB e block devices não foram liberados;
- validação focal: `31 passed`; regressão integral de produto:
  `524 passed, 1 skipped`; compileall PASS;
- prova humana de prazer, química, criação arbitrária e qualidade final:
  `PENDING_GUILHERME`;
- documento vinculante: `docs/product/CREATIVE_INTERLOCUTION_PRODUCT.md`;
- próximo passo exato: implementar correção conversacional do espelho sem
  reiniciar a criação e uma tela inicial que ofereça nomear o Guia sem comando.

## ARC-10 — convergência Hosted/Native (2026-08-18)

- Estado: `READY_FOR_GUILHERME_ARC11_HUMAN_PROOF`;
- branch/commit de base: `product/semantic-multiverse` em
  `df12e916c90d9bd2b966326275dc191573f38abd`;
- contrato compartilhado:
  `schemas/product/hosted-native-ux-contract-v1.json`;
- SHA-256 do contrato:
  `4d209cce708d843ffef50ac606ba199151be39eb9ecfff9c2c9fae233d24bcb9`;
- Native implementa validador bounded para readiness, stream ordenado, jobs com
  evidência e cancelamento terminal;
- fila de 16 eventos prioriza
  `PRESENCE > FLOW > SYSTEM > BACKGROUND > AUDIT` e falha fechada ao lotar;
- política G4 histórica não foi alterada;
- imagem Native reconstruída locked/offline e executada em QEMU/OVMF real;
- imagem:
  `product-demos/human-proof/arc-native-convergence-2026-08-18-attempt1/casulo-native-arc10.img`;
- SHA-256 da imagem:
  `a0ed1c5f3229a7a23e7dfce99e8d6a0f865bd23b70014db4afc02277c20f895f`;
- SHA-256 do manifest:
  `e9e98c6c3027df24fdc607b51125a2ddb4d0aaaa68413a6ab27bc5ac74731033`;
- boot: PASS, sem markers ausentes/proibidos; serial SHA-256
  `916d5084cfb79091ccc94437e12d101854b10924d686ee25fc5b3e8e9e9b2001`;
- QEMU: TCG, 2 vCPUs, rede off, imagem read-only, nenhum block device físico;
- validação focal: `14 passed`; produto integral: `517 passed, 1 skipped`;
  Cargo check locked/offline PASS;
- classificação:
  `NATIVE_CONTROL_PLANE_BOOT_PROOF_NOT_NATIVE_MODEL_OR_VOICE_PROOF`;
- Qwen/llama.cpp, áudio físico, DPAPI, renderer e materializador continuam
  Hosted e não foram reivindicados como drivers Native;
- Cloud `RELEASE_LOCKED`; public/owner separados; USB, QPU, benchmark
  científico, desempenho e energia não foram iniciados;
- espaço livre observado: aproximadamente `70.21 GiB`;
- próximo passo exato: Guilherme executar o launcher ARC-9 e decidir o ARC-11
  pela experiência humana; nenhuma automação aprova química/voz/design em seu
  nome.

## ARC-9 — presença contínua e interface agradável (2026-08-18)

- Estado: `READY_FOR_GUILHERME_ARC9_PLEASANT_INTERFACE_PROOF`;
- branch/commit de base: `product/semantic-multiverse` em
  `df12e916c90d9bd2b966326275dc191573f38abd`;
- worktree histórico preservado; nenhuma limpeza, reset ou reclassificação de
  evidência foi executada;
- protocolo `casulo.ux-event/1.0` separa presença, carregamento do modelo,
  tokens e lifecycle de jobs;
- tokens são publicados conforme o runtime neural os produz, sem animação
  temporal sobre bloco pronto;
- criação depois de `CONFIRMO` roda em background e emite milestones somente
  para artifacts/receipts reais com SHA-256;
- porcentagem, ETA e progresso fictício são recusados pelo validador;
- cancelamento é cooperativo e conclusão tardia não publica resultado;
- interface owner prioriza conversa e forma viva; controles técnicos estão em
  `Mais`;
- observador não persiste tokens da resposta nem conteúdo do usuário;
- evidência:
  `product-demos/human-proof/arc-pleasant-interface-2026-08-18-attempt2`;
- SHA-256 do manifest da evidência:
  `e093a3d739e2ad0d370e3334e9c9a7b70a0750f3fdee6650caecba500a4ce3d1`;
- `attempt1` preservado e superseded: ainda classificava um encerramento falho
  como resposta substantiva no observador; a interface já era recuperável;
- launcher:
  `product-demos/human-proof/monday-arc-pleasant-2026-08-18-attempt1/START_CASULO_ARC9.vbs`;
- SHA-256 do manifest do launcher:
  `922f5c12d031665809450450d1e151ffcbeafc722b120551c2c734c648f46235`;
- classificação:
  `DETERMINISTIC_UX_CONTRACT_SMOKE_NOT_OWNER_NEURAL_HUMAN_PROOF`;
- validação focal: `15 passed`; produto integral: `512 passed, 1 skipped`;
  py_compile e `git diff --check` PASS;
- voz física, beleza, química e qualidade neural não foram aprovadas pelo
  agente; continuam `PENDING_GUILHERME`;
- durante um job que ocupa o runtime neural, a presença responde com receipts
  reais, mas diálogo neural livre simultâneo ainda não é prometido;
- Cloud `RELEASE_LOCKED`; public/owner separados; rede, USB e benchmark
  científico não foram iniciados;
- espaço livre observado: aproximadamente `70.69 GiB`;
- próximo passo exato: Guilherme executar o launcher ARC-9; engenharia segue
  para ARC-10 somente preservando os contratos validados e as fricções humanas
  P0/P1 encontradas.

## ARC-8 — fronteira matemática verificável (2026-08-18)

- Estado: `READY_FOR_GUILHERME_ARC_MATH_BOUNDARY_PROOF`;
- kernel especializado: cosseno signed-hash da `LivingMemory`, representação
  densa de 64 posições substituída por coordenadas esparsas não nulas;
- equivalência: `10/10`, diferença absoluta máxima `0.0`, tolerância `1e-15`;
- perfil curto local: `65.404 ms` candidato contra `85.6974 ms` referência por
  4.000 pares/rodada; razão `0.763197`, abaixo do limiar congelado `0.95`;
- tráfego lógico: `86` posições contra `1280`; não representa bytes físicos;
- T/2.0 governa a adoção via `owner.math.boundary_policy`; receipt causal é
  consumido pelo launcher e mutação da política altera o kernel executado;
- T indisponível ou gate negado preserva o kernel denso, sem recomputar uma
  aprovação em Python;
- caminho owner Semantic Multiverse injeta a seleção na `T85ContinuityService`
  e a expõe em `:memoria`;
- Qwen/llama.cpp e Whisper/whisper.cpp continuam primitives estrangeiras;
  tensor stack histórico continua fora do caminho owner;
- evidência:
  `product-demos/human-proof/arc-math-boundary-2026-08-18-attempt1`;
- SHA-256 do manifest:
  `c2da7ca035a83d2bc8e893e5b6401a346485597621843a42cc238e4c8ad6e776`;
- validação focal: `25 passed`; produto integral: `504 passed, 1 skipped`;
  compileall PASS;
- suíte global: `938 passed, 3 skipped`; cinco testes legados de
  benchmark/paridade foram corretamente bloqueados pelo guard de aposentadoria
  científica e não receberam opt-in;
- nenhum benchmark científico, energético, PyTorch, API externa, Cloud, USB ou
  prova humana foi iniciado;
- espaço livre observado: aproximadamente `70.04 GiB`;
- próximo passo de engenharia: ARC-9, presença instantânea, streaming real e
  jobs em background sem painel técnico.

## ARC-7 — orçamento neural e contexto suficiente (2026-08-18)

- Estado: `READY_FOR_GUILHERME_ARC_BUDGET_PROOF`;
- seis operações neurais possuem budgets distintos e imutáveis: diálogo,
  reconstrução, refino, roteamento semântico, síntese T e reparo T;
- síntese falha sem confirmação humana ou requisito HARD; reparo falha sem
  diagnostic real; refino falha sem lacuna material aberta;
- policies customizadas podem reduzir, nunca ampliar, o budget roteado;
- contexto de diálogo preserva restrições e fala corrente, limita conversa e
  memória e registra toda inclusão/descarte em receipt append-only;
- chamadas estruturadas validam o prompt antes da inferência; truncamento
  implícito do runtime é negado;
- budgets cabem na janela corrente de 8.192 tokens por teto conservador em bytes
  UTF-8 + saída máxima + margem de 256 tokens;
- smoke vigente:
  `product-demos/human-proof/arc-neural-budget-2026-08-18-attempt2`;
- receipt:
  `f3849f9d2921a724b188788b57f6809b55c4b18d0aeeb594231b3e29b3237512`;
- SHA-256 do manifest:
  `d4950f34f123f45ebdf925d2a816d807c52917a5a9e6971c5dbae87e43e9d9cc`;
- `attempt1` preservado e superseded por não incluir ainda o gate em bytes;
- validação focal final: `57 passed`; regressão integral:
  `494 passed, 1 skipped`; compileall PASS;
- classificação:
  `DETERMINISTIC_BUDGET_CONTRACT_SMOKE_NOT_OWNER_NEURAL_QUALITY_PROOF`;
- qualidade neural sobre criação inédita e prova humana:
  `PENDING_GUILHERME`;
- nenhum benchmark científico, API externa, Cloud, USB ou prova humana foi
  iniciado;
- próximo passo de engenharia: ARC-8, inventário da fronteira matemática e
  especialização apenas com equivalência semântica preservada.

## ARC-6 — reparo causal (2026-08-18)

- Estado: `READY_FOR_GUILHERME_ARC_CAUSAL_REPAIR_PROOF`;
- requisito confirmado agora é ligado a `semantic_paths`, `ForgeUnit.watch_paths`
  e verificadores por `RequirementSemanticBinding`;
- requisito HARD sem unidade T reprova o candidato de síntese dentro do budget;
- diagnóstico sem requisito causal é recusado no caminho owner;
- `CausalRepairPlan` calcula sementes semânticas e fechamento somente a jusante;
- `CausalRepairReceipt` confere rebuild/reuse, preservação de hashes fora do
  subgrafo e TCAP real antes/depois;
- o worker owner persiste `requirement-semantic-bindings.json` e inclui receipts
  causais no `repair-outcome.json`;
- smoke válido: `product-demos/human-proof/arc-causal-repair-2026-08-18-attempt2`;
  `review + output` reconstruídos, `decision + identity` reutilizados, quatro
  executáveis T externos PASS;
- receipt causal:
  `024769806232a940505c97e4a9761259555e33efd6cbc12893c285a159ba0645`;
- manifest do attempt2:
  `de8f35589fce1a62f266289748dde3f680b0c55355873ec923cf8fb85c5215e7`;
- `attempt1` preservado com errata por rotular hash de ForgeReceipt como TCAP;
- validação: `22 passed` focal; regressão integral `482 passed, 1 skipped`;
  compileall PASS;
- classificação do smoke:
  `DETERMINISTIC_CONTRACT_SMOKE_NOT_OWNER_NEURAL_PROOF`;
- nenhum benchmark científico, API externa, Cloud, USB ou prova humana foi
  iniciado;
- próximo passo de engenharia: ARC-7, orçamento neural e contexto suficiente
  mínimo; prova humana continua pertencendo a Guilherme pelo launcher ARC.

## ARC — reconstrução orientada à intenção (2026-08-18)

- Estado histórico superseded por ARC-6:
  `READY_FOR_GUILHERME_ARC_INTENT_PROOF`;
- tese e roadmap vinculante:
  `docs/product/ARC_RECONSTRUCTION_ARCHITECTURE.md`;
- novo contrato first-party: `IntentTwin`, com observações
  `EXPLICIT/INFERRED/CONFIRMED`, duas hipóteses, `EpistemicGap`, seleção e
  confirmação humana fail-closed;
- reconstrutor owner: geração estruturada local de duas hipóteses e no máximo
  uma pergunta de maior ganho material;
- smoke neural real final `attempt7`: contrato/runtime e compatibilidade
  sintética PASS, Qwen local verificado e zero API externa; uma hipótese foi
  suficiente, preservou `2/2` observações HARD e evitou alternativa artificial;
  `IntentTwin` `64db666f68fd6cf06071f37a676d008cf3240e73b34176b6adb9263d94e2f7e7`;
- tentativas 1–6 e respectivas falhas/erratas foram preservadas append-only;
- divergência neural `task_kind=CONVERSATION` foi preservada; a autoridade
  determinística do comando `:criar` aplicou e registrou
  `task_kind:CONVERSATION->CREATION`;
- fluxo `:criar`: espelho visual antes de confirmação, RequirementGraph depois
  de confirmação e só então T/simulação/materialização;
- runtime Qwen já aberto é reutilizado no worker de criação: a antiga segunda
  carga do modelo foi removida dessa rota;
- `holdout scan` e a exigência artificial de primeira tentativa imperfeita
  permanecem no modo histórico de evidência e estão desativados explicitamente
  no modo `OWNER_PRODUCT_CREATION`;
- transporte `RequirementGraph -> TRequirementGraphCompiler` implementado com
  estado inicial honesto `AWAITING_INDEPENDENT_EVIDENCE`;
- `RequirementEvidenceGate` emite receipts de aceite, compile, simulação,
  execução limpa e revisão humana; qualquer HARD `FAIL/UNKNOWN` ou safety gate
  reprovado bloqueia materialização; verifier de domínio sem adapter permanece
  deliberadamente `UNKNOWN`;
- regressão completa final: `475 passed, 1 skipped`; testes IntentTwin:
  `14 passed`; compileall e Windows Script Host PASS;
- runtime neural e compatibilidade do novo contrato: PASS no escopo sintético;
  qualidade sobre criação inédita e confirmação: `PENDING_GUILHERME`;
- nenhum release T85 foi reconstruído ou alterado;
- Cloud `RELEASE_LOCKED`; guest network OFF; USB/block devices proibidos;
  benchmark científico não iniciado;
- launcher: `product-demos/human-proof/monday-arc-fast-2026-08-18-attempt1/START_CASULO_ARC.vbs`;
- próximo passo exato: Guilherme abre o launcher, usa `:criar`, fornece uma ideia
  inédita e confirma somente se o espelho representar sua intenção; o próximo
  sprint de engenharia é ARC-6 após essa prova.

## Monday Discovery M1 — perfil interativo rápido (2026-08-18)

- Estado técnico: `READY_FOR_GUILHERME_MONDAY_DISCOVERY_FAST_SESSION`;
- launcher novo e append-only:
  `product-demos/human-proof/monday-discovery-fast-2026-08-18-attempt1/START_MONDAY_DISCOVERY_FAST.vbs`;
- causa visual corrigida: o observer deixou de usar `readline()` no perfil
  rápido e agora pinta os deltas reais conforme chegam;
- causa de latência estrutural mitigada: diálogo comum não inicializa uma VM
  TCG por turno; o Qwen owner local permanece quente no host;
- `:criar` preserva ponte VM, validação, geração/reparo T, simulação e
  materialização;
- o perfil é `DISCOVERY_FAST_HOST_DIALOGUE`, não substitui o selo T85 e não é
  prova de bridge VM por resposta;
- o launcher M1 original continua com `vm-bridge` como default;
- carregamento real do modelo verificado em smoke sem geração: `25,1 s`;
- validação focal: `25 passed`, compileall PASS e os dois VBS aprovados pelo
  `cscript.exe` real;
- microfone/TTS físicos não foram abertos; benchmark científico não iniciado;
- Cloud `RELEASE_LOCKED`; guest network OFF; USB/block devices proibidos;
- SHA-256 do manifest do perfil rápido:
  `a3fc74e9c12e77861b9f2bced2997fa5af5ebfac03d8e5f7d4049ec1d724ac59`.

## Monday Discovery M1 — estado corrente (2026-08-17)

- Estado: `READY_FOR_GUILHERME_MONDAY_DISCOVERY_SESSION`;
- baseline T85 preservado: `READY_FOR_GUILHERME_CASULO_T85_VM_HUMAN_PROOF`;
- release assinado não foi alterado;
- doctor read-only: 12/12 PASS;
- regressão M1: 6 PASS;
- regressão selecionada: 46 PASS e 1 skip físico não contado;
- sessão humana e notas: `PENDING_GUILHERME` / zero;
- voz física: não aberta; consentimento literal obrigatório por sessão;
- atlas inicial: `docs/product/MONDAY_FAILURE_ATLAS_2026-08-17.md` e `.json`;
- launcher: `product-demos/human-proof/monday-discovery-2026-08-17-attempt1/START_MONDAY_DISCOVERY.vbs`;
- checkpoint M1: `73d79b3c7510401a360359b826df284d95d1fa1c943cbbecea56bc8491420afe`;
- Cloud `RELEASE_LOCKED`; guest network OFF; USB/block devices proibidos;
  QPU negada; benchmark científico não iniciado;
- design final: fora de escopo neste Goal.

O histórico abaixo permanece preservado como estados anteriores do produto.

## Revolution Closure — estado corrente (2026-08-14)

- Estado: `READY_FOR_GUILHERME_CASULO_BETA_HUMAN_PROOF`
- Branch real: `product/semantic-multiverse`
- Commit baseline preservado: `df12e916c90d9bd2b966326275dc191573f38abd`
- Último gate técnico: `RC13_HANDOFF_COMPLETE_VBSCRIPT_RESEAL`
- Handoff: `release/human-proof/START_CASULO_OWNER.vbs`
- Manifest corrente: `b6bfaa8166b0b2174392be64c1936a266e8a8cd119c9c7a8ab5e38017c2c4196`
- Compatibilidade WSH: quatro launchers Windows-1252 sem BOM aprovados pelo
  `cscript.exe` real; candidato UTF-8 BOM preservado e superseded.
- Human proof: `PENDING_GUILHERME`; nenhum resultado humano foi simulado.
- Cloud `RELEASE_LOCKED`; guest network OFF; USB/block devices proibidos;
  QPU negada; benchmark científico não iniciado; assinatura não comercial.

O histórico abaixo permanece preservado como estados anteriores do produto.

- Estado: `READY_FOR_GUILHERME_SEMANTIC_MULTIVERSE_VM_INSPECTION`
- Data: 2026-08-12
- Branch: `main`
- Baseline Git preservado: `df12e916c90d9bd2b966326275dc191573f38abd`
- Sprint atual: Generative VM Sprint 10 concluído
- Ultimo gate integral aprovado: G10 — cenário generativo integrado 16/16
- Gate corrente: `READY_FOR_GUILHERME_GENERATIVE_VM_INSPECTION`
- Gate físico de voz: `PASS_WITH_ASR_UTTERANCE_QUALITY_RISK`

## Transição vinculante

```text
scientific_goal = SUPERSEDED_BY_PRODUCT_GOAL_2026_08_11
new_scientific_benchmark_started = false
```

O worktree preexistente permanece substancialmente modificado e contém
evidências históricas não rastreadas. Nada foi apagado ou reclassificado.
`AGENTS.md` registra o objetivo product-first e bloqueia pesquisa no caminho
padrão.

O host possui cerca de `57.1 GiB` livres após limpeza auditada de caches e
remoção autorizada de cinco VMs VirtualBox órfãs. Casulo e Jaderson foram
protegidos por verificação de colisão; o VirtualBox já estava desinstalado.

## Gates aprovados

| Sprint | Gate | Evidência |
|---|---|---|
| 0 | transição/aposentadoria científica | CI/release default sem campanhas; CLI histórico exige opt-in |
| 1 | domínio/versionamento | CreationSpec, IntentDelta, políticas e invariantes |
| 2 | HAL/Hosted Shell/edições | shell SILENCE, contratos engine, wheels separados |
| 3 | T vNext Foundations | expression AST própria; record/enum/Result; linker; CFG; effects; TCAP 1.1 |
| 4 | Living Memory | log cifrado/hash chain; projeções; recall; export/delete; reabertura |
| 5 | Voice Duplex hosted | entrada e saída físicas, cancelamento por voz e ASR pt-BR reais; sentinela exata preservada como falha de qualidade |
| 6 | Guide Presence | diálogo preemptivo, jobs desacoplados, colaboração consentida e progresso por evento com evidência |
| 7 | Intent Engine / T Forge | delta conservador, confirmação humana e recompilação transacional do subgrafo afetado |
| 8 | Creation Field | quatro fases visuais derivadas de estado/receipts, fingerprints incrementais e HTML local seguro |
| 9 | Simulation Runtime | doubles first-party sem I/O, preflight global, receipts encadeados e correção localizada |
| 10 | Materializer / API local | export transacional, ZIP reprodutível, manifest/SBOM/hashes e loopback simulation-only |
| 11 | Cloud standby | gateway, auth/policy, jobs, replay/cancelamento e observabilidade; produção fail-closed |
| 12 | Installer / Machine Profile | doctor read-only, plano consentido e perfis reproduzíveis |
| 13 | Native Foundation | boot UEFI x86-64, HAL e artefato T isolado validados em QEMU |
| 14 | Product Alpha | vertical slice owner, 12 estados, round-trip, builds assinados e P0-P15 aprovados |

## Perfis

| Perfil | Estado | Fronteira atual |
|---|---|---|
| `casulo-owner` | PRODUCT_ALPHA_LOCAL_PASS | motor first-party direto, privado e offline; sem Cloud no fluxo principal |
| `casulo-public` | SIGNED_CLIENT_HARNESS_PASS | somente `CloudEngineClient` e harness; sem motor/fallback owner |
| `casulo-cloud-standby` | SIGNED_STANDBY_RELEASE_LOCKED | servidor testável; produção, DNS, bind e credenciais negados |

Prova corrente na árvore public: `12` arquivos auditados,
`private_components_absent=true`, content tree SHA-256
`175fb0203b15042130c8e1eaecdc02984673af904e6de28f5ce98b2623166e3d`.
O wheel public Alpha possui `6` arquivos, zero achado privado e content tree
SHA-256 `6ea3f750d844ec7e519a2f81c012b8b6fda2dcacb92712aba50cc8721284d9d5`.
Owner, public e cloud-standby possuem manifests, SBOMs e assinaturas Ed25519 de
desenvolvimento distintas; nenhuma chave privada integra o repositório.

## Sprint 5 entregue

- contrato PCM16 mono, captura lazy e VAD energético;
- ASR streaming por adapter com partial/final e endpointing;
- TTS por sessão cancelável e barge-in medido pelo relógio da HAL;
- transcript final entra no Hosted Shell como evento `PRESENCE`;
- engine inexistente ou locale diferente de pt-BR falha explicitamente;
- fallback Microsoft Maria pt-BR disponível, mas sem alegação de streaming PCM;
- fallback texto explícito cancela fala e não é apresentado como ASR;
- protocolo ASR JSONL assíncrono, limitado a 256 KiB por linha e sem shell;
- `casulo-voice doctor` verifica receipt/hash/binário sem criar cache ou baixar;
- worker first-party executa protocolo, limites, partial/final/reset fora do loop;
- ABI C++ estreita passou compilação contra stub do C API pinado;
- adoção exige consentimento literal, é transacional e idempotente;
- build é offline, guardado e sela bridge em receipt próprio;
- Maria pt-BR gerou 90.944 bytes PCM16 reais em memória, sem playback;
- fallback TTS é explicitamente buffered, cancelável e não redistribuído;
- `whisper.cpp`/`small-q5_1` adotado localmente com source/model/receipts verificados;
- bridge MinGW autocontido, sem DLL externa não sistêmica, e doctor prova ABI carregável;
- loopback Maria -> 198.272 bytes PCM16 -> ASR devolveu a frase pt-BR esperada;
- `base-q5_1` multi-modelo selecionado como perfil rápido local: ~1,29 s no
  smoke de 1 s/4 threads contra ~4,13 s da small, sem claim geral;
- `WindowsDirectStreamingTts` implementa playback progressivo hosted e barge-in
  por término do processo; playback físico e cancelamento foram executados;
- captura física pt-BR processou 686 frames, 68 vocais, sem persistir PCM;
- barge-in cancelou a sessão 15,8 ms após a decisão local; a frase-sentinela foi
  mal transcrita e o smoke estrito permaneceu reprovado, sem ser reclassificado;
- política repetível de recuperação de espaço protege Casulo/Jaderson por colisão de caminhos;
- todo acesso físico ocorreu após aviso e consentimento; nenhum PCM foi salvo.

## Sprint 6 entregue

- `GuidePresence` separado de workers e engines;
- modos explícitos `EXPANSION` e `CRYSTALLIZATION`;
- clarificação conservadora sem criação silenciosa de intenção;
- `CollaborationProposal` somente aplicável por aprovação humana explícita;
- pressão e campos estereotípicos negados estruturalmente;
- conflito explícito em vez de concordância servil;
- `JobEvent` com proveniência, timestamp e hash como única origem de progresso
  no caminho novo;
- eventos terminais e duplicados são rejeitados;
- Hosted Shell preserva prioridade `PRESENCE` enquanto job segue ativo;
- demonstração reproduzível `casulo-guide-demo`.

## Sprint 7 entregue

- fala final usa gramática conservadora e produz `IntentDelta.PROPOSED`;
- fala ambígua pede clarificação e nunca cria operação silenciosa;
- `confirmo` e `rejeito` são decisões humanas explícitas separadas;
- proposta não altera a `CreationSpec`;
- criação candidata compila antes do commit vivo;
- `TForge` usa o frontend T real, análise, IR geral e Metamorfose Graph;
- source alterado nunca pode se esconder atrás de `affected_paths` incorreto;
- dependências propagam impacto somente a jusante;
- build falho é transacional e preserva cache/criação anteriores;
- demonstração recompilou `behavior + interface` e preservou o hash de
  `identity`;
- nenhum atalho legado de treinamento participa do caminho.

## Sprint 8 entregue

- projeção pura de `SILENCE`, `FIRST_INTENT`, `FIRST_FORM` e `CONFIRMATION`;
- `SILENCE` sem atividade visual falsa;
- semente de intenção ligada ao hash do delta;
- primeira forma exige receipt real do T Forge;
- dependências visuais derivadas dos artifacts;
- posições estáveis e fingerprints preservados fora do impacto;
- HTML/SVG autocontido, acessível, sem JavaScript/rede e com CSP;
- animação decorativa respeita `prefers-reduced-motion`;
- cinco páginas reproduzíveis em `product-demos/creation-field-sprint8`;
- inspeção automatizada em browser ficou aberta por falha dos assets internos
  do controlador, registrada sem mascaramento.

## Sprint 9 entregue

- runtime aceita exclusivamente `SimulationCapabilityDouble` first-party;
- nenhum callback ou provider real entra no plano;
- capabilities precisam estar declaradas na criação;
- preflight integral ocorre antes da primeira tentativa;
- payload, tamanho, DAG e dependências são limitados;
- tentativas e respostas formam hash chain;
- falha interrompe dependentes e retorna caminhos locais de correção;
- a correção exige novo `IntentDelta` e confirmação humana;
- demonstração falha -> correção -> nova simulação preservou o hash de
  `identity` e declarou `real_effects_executed=false`.

## Sprint 10 entregue

- exportação exige `AGREEMENT`, simulação `PASS` e zero effect real;
- secret scanner recusa campos sensíveis e PEM antes do staging;
- destino é confinado, overwrite é negado e publicação é atômica;
- manifest, SPDX SBOM e SHA256SUMS verificam todos os payloads;
- ZIP possui ordem/timestamps congelados e hash reproduzível;
- API gerada liga somente em `127.0.0.1` e serve estado selado;
- pacote declara fronteira engine-agnostic e não contém adapter owner;
- demo materializada possui SHA-256
  `4c996a2af141b0b9ff7f8543b2bfc2fb6acb524c2f70a81c419c1e2eb226e4c3`.

## Último gate executado

```powershell
python -m compileall -q src/casulo/product tests/product
python -m pytest -q --basetemp .tmp-product-sprint5-partial-gate/pytest `
  tests/product tests/test_t_frontend.py tests/test_t_semantics_ir.py `
  tests/test_t_workspace.py tests/test_t_tcap.py tests/test_t_backend.py `
  tests/test_t_metamorphosis.py tests/test_t_native.py `
  tests/test_semantic_scheduler.py
python tools/audit_public_artifact.py editions/casulo-public
```

Resultado final: `279 passed, 1 skipped, 42 subtests passed in 12.38s`;
`cargo check` aprovado; auditorias source e wheel public com zero achado privado.

Doctor após adoção/build: `asr_pt_br=READY`, `bridge_loadable=true`,
`model_verified=true`, `source_verified=true`, `ready=true`.

## Bloqueios reais

O caminho físico hosted passou, mas a sentinela “Pare, Casulo” foi transcrita
como “Vai cadupe”. A interrupção por energia de voz funcionou; qualidade de ASR,
calibração por dispositivo e AEC continuam riscos de produto após o Alpha, sem
invalidar o fallback textual nem a presença do Guia.

TTS Maria possui duas rotas honestamente distintas: PCM buffered sem playback e
playback direto progressivo/cancelável. A segunda fecha a implementação hosted,
e foi exercitada fisicamente com consentimento. TTS redistribuível/cross-platform
continua roadmap separado; Piper ativo é GPL-3.0 e sherpa-onnx inclui eSpeak NG
GPL-3.0-or-later no caminho auditado. Nenhum deles foi adotado. LLVM foi
instalado e QEMU foi localizado fora do PATH e usado pelo runner explícito.

## Claims não autorizados

- superioridade geral sobre PyTorch/Inductor;
- vantagem energética ou energia total;
- ASR perfeito ou frase-sentinela de barge-in semanticamente aprovada;
- System.Speech apresentado como streaming PCM ou redistribuível;
- Cloud de produção disponível;
- assinatura de desenvolvimento apresentada como assinatura de release;
- release public de produção pronto;
- T substitui pesos, drivers ou kernels numéricos.

## Sprint 11 entregue

- autenticacao abstrata com principal estritamente test-only;
- policy deny-by-default para contexto remoto e treino com conteudo do usuario;
- limite de jobs em voo e backpressure observavel;
- idempotencia por request e colisao de replay rejeitada;
- cancelamento cooperativo e stream com terminal unico;
- falhas sem vazamento do texto da excecao;
- metricas agregadas com `contains_user_content=false`;
- `production_bind` negado incondicionalmente em `RELEASE_LOCKED`;
- public preservado com 12 arquivos, hash inalterado e zero componente privado.

## Sprints 12 a 14 entregues

- doctor somente leitura, Machine Profile versionado e instalação consentida;
- LLVM detectado e QEMU utilizado apenas para corretude Native, nunca benchmark;
- boot UEFI x86-64, HAL e execução isolada de TCAP reproduzidos;
- Campo da Criação cobre os 12 estados do ciclo;
- materialização possui importação fail-closed, round-trip e reedição;
- motor owner first-party liga diretamente ao pipeline geral T/T Forge;
- memória DPAPI reabre e recupera a criação com proveniência;
- simulação pausa, retoma, reproduz e compara versões sem efeitos reais;
- inteligência local first-party de referência possui registry/model cards e
  seleção de contexto que nunca descarta restrições obrigatórias;
- owner, public e cloud-standby foram empacotados e assinados separadamente;
- P0-P15 estão aprovados no Hosted Product Profile e a fundação Native passou.

## Limitações preservadas

- o Product Alpha determinístico permanece referência, mas o artifact owner
  generativo usa Qwen3-4B local verificado e não contém fake engine;
- qualidade de ASR por dispositivo, AEC e TTS redistribuível seguem no roadmap;
- assinaturas atuais são de desenvolvimento, não chaves de release/produção;
- Native ainda não possui drivers completos de áudio, GPU ou rede;
- public opera contra `CloudTestHarness`; indisponibilidade falha honestamente;
- Casulo Cloud permanece `RELEASE_LOCKED` e não possui endpoint de produção.

## Claims não autorizados do Alpha

- superioridade geral sobre PyTorch, Inductor ou qualquer engine;
- vantagem energética, energia total ou reprodução de `8.957846x`;
- ASR perfeito, Native completo ou Cloud de produção disponível;
- inteligência determinística apresentada como LLM/pesos generativos;
- assinaturas de desenvolvimento apresentadas como release comercial;
- T apresentado como substituto de pesos, drivers ou kernels numéricos.

## Proximo passo exato

### Checkpoint da inspeção Semantic Multiverse 3

Estado corrente: `IN_PROGRESS_CHECKPOINTED`. A CreationSpec Einstein sem nome
foi preservada; o renderer agora usa projeção tipada total, erros visuais são
recuperáveis e restore ausente não produz traceback. A criação original não era
solver. Uma nova rota neural materializou um avaliador local 4D que constrói
conexão, Ricci, escalar, tensor de Einstein e resíduos, com escopo e recusas
explícitos. Produto: `259 passed, 1 skipped`; Native e fronteira public passam.
Cloud segue `RELEASE_LOCKED`; nenhum benchmark científico foi iniciado.

Executar `release/CASULO_OWNER_VM_INSPECT.ps1`, conversar e criar livremente,
registrar fricções com `:nota` e exportar o feedback com `:export`, sem
desbloquear Cloud/public/USB nem iniciar benchmark científico.

## 2026-08-20 — port neural Native NP3

Estado: `NATIVE_WEIGHT_FORMATS_VALIDATED_FIRST_TOKEN_PENDING`.

- parser GGUF v3 `no_std` e projeção Qwen3 implementados em
  `os/native-model`;
- bytes autênticos F32, Q4_K e Q6_K do Qwen3-4B adotado consumidos no kernel;
- erro Q4_K dos probes NP1/NP2 falsificado, formalmente invalidado e corrigido;
- NP3 passou 3/3 boots QEMU read-only com resultados numéricos idênticos;
- inventário integral contabiliza 398 tensores e 2.491.323.904 bytes de payload;
- modelo completo não está mapeado e nenhum token derivado dos pesos foi
  produzido;
- Cloud segue `RELEASE_LOCKED`; rede guest OFF; nenhum USB/block device físico
  foi acessado; nenhum benchmark científico foi iniciado.

Evidência e contrato seguinte:

- `docs/product/NATIVE_NEURAL_PORT_EXECUTION_STATE.md`;
- `docs/product/NATIVE_QWEN_RUNTIME_PLAN.md`;
- `outputs/casulo/native-neural-port/2026-08-20-np3/`.

Próximo gate: `NP4_NATIVE_MODEL_PAGED_IO`, lendo o GGUF completo read-only e
content-addressed sem duplicar os pesos e sem tentar colocá-los no heap de
2 MiB. Primeiro token permanece reservado a NP8, depois de tokenizer,
embedding, um bloco, 36 blocos, logits e verificação independente.

## 2026-08-20 — port neural Native NP4

Estado: `NATIVE_COMPLETE_MODEL_PAGED_IO_VALIDATED_FIRST_TOKEN_PENDING`.

- o modelo owner completo de 2.497.280.256 bytes foi exposto ao guest por um
  item QEMU `fw_cfg` DMA read-only com nome exato e cache bounded;
- o parser GGUF paginado percorreu 28 metadados e 398 descritores sem
  materializar o modelo inteiro;
- tensores F32, Q6_K e Q4_K foram localizados dinamicamente e bytes autênticos
  do início, meio e cauda foram consumidos;
- 5.375.232 bytes foram carregados pelo cache no probe, 0,215243% da fonte;
  isso é contabilidade de I/O esparso, não compressão ou desempenho;
- controles de item ausente, truncamento, corrupção e offset inválido foram
  rejeitados fail-closed;
- validação: 16 testes Python PASS, 7 testes Rust PASS e 3/3 boots definitivos;
- modelo e imagem permaneceram imutáveis; rede guest OFF; nenhum dispositivo
  físico foi anexado ou escrito;
- nenhum token e nenhuma inferência neural completa foram executados.

Evidência:

- `docs/product/NATIVE_MODEL_PAGED_IO_EXECUTION_STATE.md`;
- `outputs/casulo/native-neural-port/2026-08-20-np4/`;
- `release/casulo-native-neural-port-np4.img`.

Próximo gate: `NP5_TOKENIZER_AND_EMBEDDING`. O tokenizer deve consumir
vocabulário/merges do GGUF bounded, ser comparado ao runtime owner e realizar
lookup Q6_K de embedding com receipts e controles negativos. Primeiro token de
saída continua reservado a NP8.

## 2026-08-21 — port neural Native NP5

Estado: `NATIVE_BOUNDED_TOKENIZER_AND_EMBEDDING_VALIDATED_ONE_BLOCK_PENDING`.

- tokenizer GPT-2/Qwen2 lido do GGUF owner: 151.936 tokens e 151.387 merges;
- `Casulo`, `hello world` e `Olá, Casulo.` coincidiram exatamente com o
  `llama-tokenize.exe` b10362 offline;
- token `49242` selecionou e dequantizou uma linha autêntica Q6_K de 2.560 F32;
- hashes integrais de tokens, tipos, merges, template e embedding passaram;
- special tokens e scripts não latinos continuam fora do escopo e são
  recusados fail-closed;
- chat template, Transformer, logits, sampling e token de saída não foram
  executados;
- 21 testes Python, 9 testes Rust e 3/3 boots definitivos passaram;
- duas falhas intermediárias foram preservadas: console CP-1252 e builder
  apontando ao pack histórico v1. O default agora usa o pack corrigido v3;
- Cloud segue `RELEASE_LOCKED`; rede guest OFF; nenhum dispositivo físico foi
  anexado ou escrito; nenhum benchmark científico foi iniciado.

Evidência:

- `docs/product/NATIVE_TOKENIZER_EMBEDDING_EXECUTION_STATE.md`;
- `outputs/casulo/native-neural-port/2026-08-20-np5/`;
- `release/casulo-native-neural-port-np5-attempt-3.img`.

Próximo gate: `NP6_ONE_TRANSFORMER_BLOCK`, com RMSNorm, projeções, Q/K norm,
RoPE, GQA, SwiGLU e residuais confrontados por tensor com oráculo independente.

## 2026-08-21 — port neural Native NP6

Estado: `NATIVE_ONE_COMPLETE_QWEN3_BLOCK_VALIDATED_36_BLOCKS_PENDING`.

- bloco zero Qwen3 completo executado no Casulo Native para o token autêntico
  `49242`;
- 19/19 estágios comparados com oráculo independente, mismatch mask zero;
- 7 matvecs, 394.240 blocos quantizados, 100.925.440 MACs e arena de 259.328
  bytes contabilizados;
- prefetch read-only bounded de 256 KiB reduziu VM exits sem copiar o modelo;
- 3/3 boots WHPX definitivos reproduziram SHA-256
  `487179f486f1df8a132b66f7ef1f542a4f1a8768278dfe67d8e5bcaab77b0b51`;
- host Rust complementar: dois tokens e 38/38 estágios PASS;
- 31 testes Python focais e 14 testes Rust PASS;
- imagem autoritativa:
  `release/casulo-native-neural-port-np6-attempt-4.img`, SHA-256
  `65a9b4360ef56355aececd16731ed33d4f508b82d6aff2043d75abc05624fef0`;
- logits, sampling e output token continuam não executados;
- Cloud `RELEASE_LOCKED`, rede guest OFF, nenhum dispositivo físico escrito,
  nenhum benchmark científico/energético iniciado.

Evidência:

- `docs/product/NATIVE_TRANSFORMER_BLOCK_EXECUTION_STATE.md`;
- `outputs/casulo/native-neural-port/2026-08-21-np6/`.

Próximo gate: `NP7_ALL_36_BLOCKS_AND_LOGITS`, com KV bounded, cancelamento por
bloco, 36 blocos, RMSNorm final e logits comparados antes de qualquer sampling.

## 2026-09-19 — CASULO FAMILY RP0.1 Day 2

Estado: `LOCAL_MODEL_120_MINUTE_STABILITY_PASS_DAY3_PENDING`.

- runtime oficial llama.cpp `v0.4.1`/build `b10964`, commit
  `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`, congelado e verificado;
- modelo local primário Qwen2.5-7B-Instruct Q2_K, revisão
  `293ca9a10157b0e5fc5cb32af8b636a88bede891`, Apache-2.0;
- perfil primário Vulkan, contexto 8192, F16 KV, quatro threads, uma geração,
  `127.0.0.1` somente; perfil CPU equivalente preservado como fallback;
- português, JSON Schema, tool calling, edição de código e
  cancelamento/recuperação passaram nos perfis primário e fallback;
- janela contínua final: 7.201,414 segundos, 119 inferências, zero falhas,
  RAM disponível mínima 1.157.832.704 bytes e disco livre mínimo
  105.290.420.224 bytes;
- 120 amostras de contadores do processador tiveram flags de limite zero e
  limite de desempenho nunca abaixo de 100%; temperatura absoluta permanece
  `UNAVAILABLE`, sem claim térmico;
- regressão focal: 23 passed; regressão Family + Product: 730 passed,
  1 skipped; testes históricos continuaram bloqueados pela política ativa;
- nenhum listener LAN, regra de firewall, certificado, API paga, inferência
  cloud, ASR, TTS ou PWA foi introduzido.

Evidência: `docs/product/CASULO_FAMILY_RP01_DAY2_LOCAL_MODEL.md` e
`evidence/family/day2/`.

Próximo gate autorizado: Dia 3, conectar o adapter do modelo loopback ao
supervisor Family e validar streaming, cancelamento, fila e backpressure com
uma única geração pesada. O Dia 3 não foi iniciado nesta sessão.
