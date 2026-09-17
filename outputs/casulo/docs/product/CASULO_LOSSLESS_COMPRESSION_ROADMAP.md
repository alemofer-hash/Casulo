# Casulo — roadmap de compressão sem perda verificável

Estado em 2026-09-10:
`CV1_7_TEMPORAL_PATH_PASS_NATURAL_SIGNAL_REJECTED`.

## Objetivo central

Executar duas provas reais, reproduzíveis e difíceis de ignorar:

1. um vídeo realmente 8K obtido de fonte pública identificada;
2. um conjunto de dados realmente contendo 100 milhões de registros.

No banco, o Casulo precisa reconstruir a entrada bit a bit. No vídeo CASV, deve
reconstruir pixels e áudio canônicos exatamente, com SHA-256 próprios, e
competir em tamanho com o arquivo recebido e baselines maduros. Arquivos
sintéticos servem somente para testes de software; nunca substituem essas duas
provas.

## Reorientação: o artefato final é CASV

O caminho principal de vídeo não produzirá um MP4 menor nem guardará HEVC dentro
de outro envelope. MP4/HEVC passa a ser somente uma fonte de importação. O
artefato canônico será `.casv`: um programa visual causal contendo estrutura,
aparência, dinâmica e residual exato.

O contrato primário muda de identidade do contêiner para identidade da mídia:

```text
decode canônico da fonte -> X
CASV -> decoder independente -> X'
SHA-256(X) == SHA-256(X')
```

O tamanho do CASV continuará sendo comparado ao MP4 recebido e aos baselines.
Comparação somente contra RGB cru é regressão de engenharia, não prova externa.
Uma trilha histórica de reconstrução byte-exact do MP4 permanece preservada,
mas não define o produto CASV.

## Limite físico que não será escondido

Nenhum compressor sem perda pode reduzir quase 100% de **todo** arquivo. Pelo
princípio da contagem, há mais entradas possíveis de tamanho `N` do que códigos
menores que `N`; entradas já comprimidas ou de alta entropia podem crescer. A
hipótese falsificável do Casulo é mais estreita:

> dados reais possuem estrutura, repetição ou estado suficiente explorável que
> uma política Casulo especializada pode remover do trânsito, mantendo uma
> reconstrução integral verificável.

Uma expansão é resultado negativo válido, não um erro a ser ocultado.

## Arquitetura

```text
fonte imutável
  -> probe de formato e SHA-256
  -> segmentação bounded em streaming
  -> identidade content-addressed por segmento
  -> deduplicação exata
  -> seleção conservadora de codec por segmento
  -> contêiner determinístico
  -> reconstrução independente
  -> SHA-256 da fonte == SHA-256 restaurado
  -> relatório contra zstd e 7-Zip
```

LC1 permanece como controle genérico de chunks fixos. O slice LC3 possui CDC
determinístico, parsing ISO BMFF/HEVC, duas IRs reversíveis
`base + dynamics + residual`, transforms locais e seleção causal T. A extensão
GOP mapeia todas as access units/NALs, trabalha com amostras completas e testa
uma referência inter-amostra explícita. O decoder independente nunca extrai
caminhos do ZIP e recusa schema, codec, tamanho, hash, receipt ou entrada
inesperados. A codificação colunar permanece futura.

CASV/0.1 acrescenta um contêiner binário próprio e um renderer RGB8
determinístico. No primeiro corte, `base` contém geometria/material, `dynamics`
contém movimento linear e `residual` fecha o XOR exato. Nenhum payload MP4 ou
HEVC é permitido dentro do arquivo. O decoder independente não importa o
encoder, a IR, o proposer ou o runtime T.

## Critério congelado antes das provas

Gate comum obrigatório:

- fonte real e licença/origem registradas;
- metadados e tamanho observados antes da compressão;
- SHA-256 da fonte calculado em streaming;
- restauração integral por cada braço;
- tamanho e SHA-256 restaurados idênticos;
- nenhum baseline falho contado como vitória;
- tempo, pico de memória e bytes temporários reportados;
- fonte, protocolo, comandos e versões selados antes do resultado.

Classificação por tamanho, sempre contra o **menor baseline bit-exact**:

| Classe | Condição predefinida |
|---|---|
| `BREAKTHROUGH_CANDIDATE` | redução >= 90% da fonte e arquivo >= 50% menor que o melhor baseline |
| `SUBSTANTIAL_ADVANTAGE` | pelo menos 25% menor que o melhor baseline |
| `MATERIAL_ADVANTAGE` | pelo menos 10% menor que o melhor baseline |
| `SMALL_ADVANTAGE` | entre 5% e 10% menor que o melhor baseline |
| `COMPETITIVE` | dentro de +/-5% do melhor baseline |
| `NEGATIVE` | mais de 5% maior que o melhor baseline |
| `INVALID` | round-trip, fonte, protocolo ou baseline inválido |

Essas faixas não autorizam alegação universal.

## Prova A — vídeo 8K real

Precondições a congelar antes do download:

- arquivo público diretamente transferível e licença/proveniência registradas;
- stream principal com pelo menos 7680x4320 confirmado por `ffprobe`;
- duração mínima de 10 segundos e pelo menos 300 frames;
- contêiner e codec originais preservados;
- fonte preferencialmente <= 20 GiB para manter a reserva operacional.

Braços:

1. fonte original, sem transformação;
2. zstd 1.5.7 nível 19, uma thread;
3. 7-Zip 26.03 Ultra, uma thread;
4. Casulo genérico;
5. Casulo estrutural histórico;
6. CASV `EXACT_MEDIA`, somente depois dos gates CV1-CV5.

Há três perguntas separadas:

- **bit-exact do arquivo:** o contêiner original inteiro é reconstruído;
- **media-exact CASV:** pixels e amostras de áudio canônicos são idênticos,
  ainda que o contêiner mude;
- **perceptual:** a saída parece equivalente, mas é necessariamente uma trilha
  com perda e não satisfaz a prova sem perda.

A prova primária do produto CASV é `EXACT_MEDIA`. A prova bit-exact histórica
permanece como controle de arquivo. As duas identidades e seus hashes devem ser
publicados separadamente; nenhuma delas pode esconder alteração da outra.

## Prova B — 100 milhões de registros reais

O candidato inicial é ClickBench `hits_compatible`, criado a partir de
pageviews de produção anonimizadas e disponibilizado em 100 milhões de linhas.
A identidade final da fonte, a licença e o tamanho remoto ainda serão congelados
por HEAD/checksum antes do download. Se o requisito permanecer especificamente
"dataset de treinamento", uma fonte de ML com 100 milhões de exemplos deve ser
selecionada sem chamar linhas analíticas de exemplos de treino.

Braços mínimos:

1. arquivo oficial na representação recebida;
2. zstd e 7-Zip bit-exact;
3. Casulo genérico;
4. Casulo colunar reversível;
5. baseline nativo do formato, quando aplicável.

O oráculo de contagem é DuckDB 1.5.5. O gate exige 100.000.000 registros e
validação de schema, nulos, ordem, tipos, conteúdo e hash. Equivalência lógica
e identidade binária serão reportadas separadamente.

## Plano de armazenamento

Espaço observado após a preparação: cerca de 165,5 GiB. Reserva rígida: 30 GiB.

```text
C:\CasuloLab\
  incoming\       fontes imutáveis e downloads retomáveis
  campaigns\      protocolos e resultados append-only
  work\            temporários de um único braço
  restored\        restauração sob verificação
  quarantine\      fontes ou outputs recusados
```

Nunca manter simultaneamente todas as restaurações gigantes. Cada braço é
restaurado, hasheado e liberado de `work` somente por uma ação de limpeza
explicitamente vinculada ao campaign manifest. Evidência e fontes não são
apagadas silenciosamente.

## Dependências qualificadas

| Ferramenta | Versão | Papel | Licença observada | Estado |
|---|---:|---|---|---|
| FFmpeg/ffprobe Gyan full | 9.0.1 | probe e controles de vídeo | GPL-3.0-or-later no build instalado | READY |
| zstd | 1.5.7 | baseline geral | BSD-3-Clause | READY |
| 7-Zip | 26.03 | baseline de arquivo | LGPL-2.1-or-later + restrição unRAR | READY |
| DuckDB CLI | 1.5.5 | oráculo de 100M linhas | MIT | READY |
| aria2 | 1.37.0 | download retomável | GPL-2.0-or-later | READY |

Nenhuma dessas ferramentas é apresentada como tecnologia proprietária do
Casulo. Redistribuição será decidida separadamente após revisão de licença.

## Sprints

### LC0 — freeze, disco e toolchain — PASS

- Steam/GTA e Unity removidos por autorização do proprietário;
- mais de 139 GiB recuperados;
- ferramentas instaladas, executadas e identificadas por SHA-256;
- nenhuma fonte Casulo/Jaderson removida.

### LC1 — núcleo sem perda e laboratório — PASS

- arquivo `.casulo` determinístico e content-addressed;
- deduplicação exata;
- codecs raw/zlib/lzma escolhidos somente quando reduzem o chunk;
- pack, inspect, verify e unpack;
- corrupção e overwrite falham fechados;
- baseline zstd/7-Zip com restauração obrigatória;
- `video-probe` e `doctor` executáveis.

### LC2 — protocolo e aquisição real — PARTIAL PASS

- vídeo 8K adquirido, identificado, hasheado e confirmado por `ffprobe`;
- escolher a fonte de 100M registros ou exemplos;
- gerar manifests de aquisição append-only;
- downloads retomáveis e quarentena de fonte divergente.

### LC3 — perfil estrutural de vídeo — V1 PASS

- entropia, boxes, `hvcC`, sample tables e NAL headers medidos sem alterar a fonte;
- contêiner, payloads e metadados particionados reversivelmente;
- CDC e cinco transforms possuem inversas e fallback raw;
- decoder independente e corrupção fail-closed aprovados;
- 64/600 samples inspecionados; análise completa de GOP/tiles/CABAC permanece aberta;
- probe curto foi bit-exact, mas expandiu 1,820171% com todo overhead contabilizado.

### LC3.1 — access units e GOP causal — PATH PASS / COST REJECTED

- as 600 samples e 1.200 NAL units da fonte foram mapeadas em três grupos GOP
  com leitura bounded de headers;
- corpus alinhado a duas samples completas, iniciado em IRAP, com 60.229.738
  bytes e partição exata `base + dynamics + residual`;
- candidate `xor-reference-prefix-zlib` realmente executou sobre a segunda VCL
  usando a VCL anterior, mas expandiu 334 bytes e não foi escolhido;
- zlib isolado economizou 58.949 bytes no corpo VCL; os payloads reduziram
  0,097913%, insuficiente para pagar a evidência do archive;
- archive padrão expandiu 4.016 bytes (`+0,0066678025%`) e o juiz T retornou
  `REJECT`;
- mutação somente em T mudou 9 para 4 invocações, transforms, trabalho e hash;
- reconstrução independente dos dois braços e manifesto 112/112 passaram;
- 74 testes integrados passaram;
- evidência: `C:\CasuloLab\campaigns\2026-09-10-hevc-gop-causal-probe-attempt4`;
- a execução ainda não representa um GOP completo nem o vídeo integral.

### CV0 — formato visual causal próprio — BOUNDED PASS

- `.casv` binário próprio implementado; não é ZIP, MP4 ou HEVC encapsulado;
- equivalência `EXACT_MEDIA` definida separadamente de identidade do contêiner;
- representação explícita `base + dynamics XOR residual`;
- renderer RGB8 inteiro e independente de floating point;
- decoder stdlib-only independente com limites, hashes e publicação atômica;
- T escolhe entre generativo, zlib canônico e raw antes do commit, e julga o
  custo do arquivo inteiro após reconstrução independente;
- mutação somente em T alterou `GENERATIVE_EXACT` para `CANONICAL_RAW`;
- probe estruturado sintético: 373.248 -> 2.591 bytes, 99,305823474% contra RGB
  cru, residual zero e round-trip exato;
- controle de ruído: 373.248 -> 375.393 bytes, veredito `REJECT`;
- a redução sintética não é evidência de vídeo natural nem vantagem sobre HEVC;
- evidência:
  `C:\CasuloLab\campaigns\2026-09-10-casv-native-format-probe-attempt1`.

### CV1 — importer e player — PASS VIDEO-ONLY / AUDIO PENDING

- adaptador FFmpeg importa um prefixo/crop bounded sem embutir o source
  bitstream e registra fonte, ferramenta, versão e hashes;
- player de referência abre `.casv` real via decoder independente e ffplay,
  sem reter o temporário ao terminar;
- probe real derivado da fonte 8K importou 2 frames de um crop 256x144 e
  reconstruiu os 221.184 bytes RGB8 exatamente;
- no crop natural, `GENERATIVE_EXACT` custou 65.654 bytes contra 64.852 bytes
  do zlib canônico; T escolheu corretamente `CANONICAL_ZLIB`;
- a proposição explicou somente 3.379 de 73.728 pixels (4,58%); portanto o
  modelo visual atual é insuficiente para vídeo natural;
- uma segunda rota preservou os 442.368 bytes do fluxo decodificado
  `yuv444p10le`; archive de 98.485 bytes, round-trip exato e fallback zlib
  escolhido por T porque o renderer de 10 bits ainda não existe;
- o player agora envia RGB8 ou `YUV444P10LE` por pipe, sem arquivo temporário;
- a rota CV1.3 conecta FFmpeg stdout diretamente ao encoder segmentado, sem
  arquivo raw intermediário; ainda faltam renderer generativo de precisão
  nativa e áudio no container;
- evidência:
  `C:\CasuloLab\campaigns\2026-09-10-casv-8k-import-plumbing-attempt1` e
  `C:\CasuloLab\campaigns\2026-09-10-casv-8k-native10-import-attempt2`.

### CV1.2 — container streaming — ENGINEERING PASS

- CASV/0.2 com escrita forward-only, manifesto/footer e 27 segmentos no probe;
- decoder independente bounded e incremental;
- extração seletiva valida índice hasheado e somente segmentos tocados, sem
  alegar verificação integral;
- player de duas passagens verificadas envia segmentos direto ao ffplay;
- 27 decisões T distintas vinculadas a índice e hash do bloco;
- corpus sintético misto: 110.592 -> 68.344 bytes, 13 segmentos raw e 14 zlib;
- 18 testes CASV e 92 testes integrados passaram;
- essa razão contra raw sintético não é evidência contra HEVC nem vídeo natural;
- evidência:
  `C:\CasuloLab\campaigns\2026-09-10-casv-stream-v02-probe-attempt4`.

### CV1.3 — importação direta — ENGINEERING PASS

- hash da fonte e plano de decode são congelados antes do processo;
- FFmpeg stdout alimenta CASV/0.2 com backpressure e sem raw intermediário;
- tamanho exato, EOF e exit code zero são precondições do rename atômico;
- testes recusam stream curto, stream longo e produtor que falha após emitir
  bytes válidos;
- probe real sobre dois quadros de crop 256x144 da fonte 8K preservou 442.368
  bytes `YUV444P10LE` com SHA-256 exato;
- `.casv` 102.753 bytes, sete segmentos zlib e redução de 76,772054036% apenas
  contra raw canônico;
- player incremental, 27/27 hashes e 163 testes integrados passaram;
- contrato de áudio canônico foi implementado e testado, mas CASV/0.2 continua
  vídeo-only;
- evidência:
  `C:\CasuloLab\campaigns\2026-09-10-casv-8k-direct-pipe-attempt1`.

### CV1.4 — programa causal segmentado — ENGINEERING PASS

- CASV/0.3 serializa `base + dinâmica + residual XOR` por grupo de quadros;
- renderer e decoder independente operam em RGB8 e `YUV444P10LE` planar;
- T escolhe por segmento entre programa, zlib e raw usando custos observados;
- mutação somente T forçou raw, mudou TCAP/receipt/storage e preservou o hash
  canônico;
- probe sintético executou programas com residual zero e recusou ruído que
  expandia;
- em dois quadros de crop natural, programa 93.569 bytes contra zlib 94.890,
  economia de payload de 1,392%; o archive completo ainda perdeu 645 bytes
  para o melhor archive histórico por overhead de proveniência;
- em oito quadros, programa 357.828 contra zlib 363.549, economia de payload de
  1,574%; archive 363.402 bytes;
- menos de 0,8% dos pixels naturais foram previstos exatamente e o decode de
  oito quadros 8K antes do crop levou 126 s: modelo e custo ainda são fracos;
- o frame-group 0.3 recusa 8K nativo porque um quadro YUV10 excede 64 MiB;
- 90 testes de compressão e 61 testes T passaram, além de 42 subtests;
- evidência:
  `C:\CasuloLab\campaigns\2026-09-10-casv-program-v03-synthetic-attempt1`,
  `C:\CasuloLab\campaigns\2026-09-10-casv-program-v03-real-crop-attempt1` e
  `C:\CasuloLab\campaigns\2026-09-10-casv-program-v03-real-clip8-attempt1`.

### CV1.5 — spatial tiling bounded — ENGINEERING PASS

- CASV/0.4 divide RGB8 em faixas e YUV10 em plano/faixa/tile, preservando a
  ordem canônica sem alocar quadro inteiro;
- layout aritmético de um quadro 8K YUV10: 102 registros, 1.632 tiles, faixa
  máxima 2 MiB; isso não equivale a encode 8K executado;
- candidatos reais por tile: DC/XOR+zlib, Paeth+zlib, zlib e raw;
- runtime T batch amortiza startup por faixa, mas preserva uma execução e um
  receipt causal por tile;
- mutação somente T muda storage e TCAP sem mudar o SHA-256 reconstruído;
- decoder independente valida e reconstrói uma faixa por vez;
- no crop natural de dois quadros, payload de tiles 83.650 bytes e record
  stream 86.170 contra zlib global 94.890: sinais de 11,845% e 9,190%;
- manifesto de 16.271 bytes apagou o sinal e levou o archive a 102.497 bytes,
  8,017% maior que zlib global;
- 56 testes CASV/T, runtime Rust, lint e probe 7/7 passaram;
- evidência:
  `C:\CasuloLab\campaigns\2026-09-10-casv-tiled-v04-synthetic-attempt2` e
  `C:\CasuloLab\campaigns\2026-09-10-casv-tiled-v04-real-crop-attempt2`.

### CV1.6 — índice binário compacto e juízo integral — ENGINEERING PASS

- CASV/0.5 remove o manifesto JSON do bitstream e deriva a geometria pelo
  header fixo;
- overhead: 156 bytes fixos + 44 por record + 5 por tile;
- T recebe o custo completo após reconstrução independente e decide publicação
  contra zlib global, não apenas contra raw;
- estados `ACCEPT_BEATS_REFERENCE`, `ACCEPT_RAW_ONLY` e `REJECT` são
  mutuamente explícitos;
- no mesmo crop real selado: archive 84.958 bytes contra zlib 94.890, ganho
  líquido de 9.932 bytes / 10,4669%;
- o hash canônico de 442.368 bytes permaneceu
  `eb1c094a58e0c79aa7a75075c31638cd20b884a7526b0786bf16342730bc3aa8`;
- artifacts forenses de autoridade somam 191.958 bytes e não foram escondidos:
  archive + auditoria perdem para zlib, embora o playback precise apenas do
  archive;
- 78 testes CASV, 19 testes compact/import e 3 testes Productive T batch
  passaram; manifests finais conferiram 147/147 e 48/48 entradas;
- evidência:
  `C:\CasuloLab\campaigns\2026-09-10-casv-compact-v05-synthetic-attempt5` e
  `C:\CasuloLab\campaigns\2026-09-10-casv-compact-v05-real-crop-repack-attempt4`.

### CV1.7 — predição temporal homóloga — ENGINEERING PASS / NATURAL NEGATIVE

- CASV/0.6 adiciona XOR e subtração modular contra o tile homólogo do quadro
  anterior, com keyframes e fallback espacial explícitos;
- encoder e decoder usam spool rotativo limitado a um quadro anterior, sem
  carregar o vídeo integral;
- T decide cada tile e o juízo final; mutação somente T demonstrou causalidade
  no controle sintético, que selecionou oito tiles temporais e passou 9/9
  gates;
- no clip natural de oito quadros, nenhuma das 252 oportunidades temporais foi
  escolhida: spatial 280.489 bytes, SUB 375.957 e XOR 412.207;
- archive CASV 326.603 bytes: 10,1626% menor que zlib, mas 10,5349% maior que
  zstd, 22,2454% maior que x265 lossless e 66,9971% maior que FFV1;
- os quatro braços reconstruíram exatamente 1.769.472 bytes com SHA-256
  `afb40c79c9a6d3bb2b6a9a73800da4eb9a9a183ed3761eac2ded71d4d67b98`;
- 93 testes CASV e 3 Productive T batch passaram; o resultado competitivo é
  negativo e não foi reclassificado;
- evidência:
  `C:\CasuloLab\campaigns\2026-09-10-casv-temporal-v06-synthetic-attempt2` e
  `C:\CasuloLab\campaigns\2026-09-10-casv-temporal-v06-real-clip8-attempt2`.

### CV1.8 — compensação de movimento inteira — ENGINEERING PASS / BRANCH REJECTED

- CASV/0.7 implementou busca inteira bounded no quadro anterior, com vetor
  assinado `(dx,dy)` pago no payload, keyframes e reconstrução independente;
- T escolheu causalmente entre oito modos; uma mutação somente T mudou TCAP,
  trace, seleção e tamanho no controle deslocado sintético;
- três holdouts naturais 80×144 por oito quadros foram congelados antes da
  implementação e confrontados com zstd, FFV1 e x265 lossless exatos;
- 13.104 vetores foram examinados por holdout, mas zero foram selecionados;
  Paeth continuou dominando;
- razões CASV/FFV1: 1,712257, 1,739936 e 1,783692; média geométrica 1,745048;
- vitórias materiais: zero; engineering `PASS`, competitive `FAIL`;
- o protocolo determinou
  `REJECT_MOTION_BRANCH_AND_ADVANCE_TO_CAUSAL_VISUAL_GRAMMAR`;
- 103 regressões CASV passaram e 393/393 hashes da campanha conferiram;
- evidência:
  `C:\CasuloLab\campaigns\2026-09-11-casv-motion-v07-natural-holdouts-attempt1`.

Próximo gate: CV2 com gramática visual causal multiescala, mantendo residual
exato e holdouts novos pré-registrados. Áudio exige uma versão audiovisual e
nenhum resultado 0.7 pode ser reclassificado.

### CV2 — gramática visual ampliada

- layers, alpha, gradientes, curvas, antialiasing e luz espacial determinísticos;
- texturas e detalhe procedural com versões explícitas;
- contabilidade fria e amortizada de renderer/modelos compartilhados.

### CV3 — compilador inverso causal

- propostas estruturais e neurais tratadas como não confiáveis;
- busca Minimum Description Length dentro de famílias declaradas;
- T governa proposta permitida, working set, equivalência e aceitação;
- residual exato mede tudo que a explicação não reconstruiu.

### CV4 — vídeo temporal natural

- tracking, câmera, oclusão, deformação e mudanças de iluminação;
- áudio e sincronização;
- holdouts pré-congelados, controles adversariais e conteúdo fora da família.

### CV5 — prova natural crescente

- clips curtos em classes diferentes;
- comparação com source codec e baselines, não somente RGB cru;
- nenhum avanço se o residual dominar ou o custo total não fechar.

### CV6 — prova 8K integral

- executar somente depois dos gates CV1-CV5;
- publicar tamanho marginal, cold-system, amortizado e custo de reconstrução;
- preservar expansão ou derrota sem reclassificação.

### LC4 — primeira prova 8K

- executar os braços congelados;
- reconstruir cada resultado;
- publicar todos os tamanhos e derrotas;
- decidir se há sinal para otimização ou falsificação da hipótese.

### LC5 — perfil estrutural de 100M registros

- inferência de schema sem perda;
- partição colunar, dicionários, delta, bit packing e null maps;
- chunks content-defined em implementação nativa;
- working set limitado e retomada transacional.

### LC6 — prova do banco

- contar 100M registros por oráculo independente;
- executar braços congelados;
- restaurar e validar conteúdo/ordem/schema/hash;
- reportar bytes por registro e custo end-to-end.

### LC7 — autoridade T — TRANSFORM SURFACE PASS

- T planeja a família de candidates e seleciona a transform persistida;
- decisões atravessam AST, semântica, IR, grafo, TCAP e runtime Rust;
- mutação causal mudou 19 para 7 invocações e o transform trace;
- primitives estrangeiras executam a política e são manifestadas;
- segmentação, dicionário, working set global e aceitação da campanha ainda não migraram.

### LC8 — runtime nativo e produto

- migrar caminho quente para Rust/C somente após profiling;
- streaming, pause/resume, recuperação e limite de disco;
- interface Stark + Jobs reduzida a escolher fonte e acompanhar prova real;
- exportar contêiner, verificador e receipt portátil.

## Comandos atuais

```powershell
python -m casulo.compression.cli doctor
python -m casulo.compression.cli pack <fonte> <arquivo.casulo>
python -m casulo.compression.cli verify <arquivo.casulo>
python -m casulo.compression.cli unpack <arquivo.casulo> <restaurado>
python -m casulo.compression.cli video-probe <video>
python -m casulo.compression.cli baseline <fonte> <diretorio-novo>
python -m casulo.compression.cli structural-analyze <video.mp4>
python -m casulo.compression.cli structural-pack <video.mp4> <arquivo.zip> --evidence-dir <diretorio-novo>
python -m casulo.compression.cli structural-verify <arquivo.zip>
python -m casulo.compression.cli structural-unpack <arquivo.zip> <restaurado.mp4>
python -m casulo.compression.cli structural-probe <video.mp4> <diretorio-novo>
python -m casulo.compression.cli gop-analyze <video.mp4>
python -m casulo.compression.cli gop-probe <video.mp4> <diretorio-novo>
python -m casulo.compression.cli gop-verify <arquivo.casulo-gop.zip>
python -m casulo.compression.cli gop-unpack <arquivo.casulo-gop.zip> <corpus-restaurado.bin>
python -m casulo.compression.cli casv-pack <frames.rgb> <video.casv> --width <w> --height <h> --frames <n> --fps-numerator <fps> --evidence-dir <diretorio-novo>
python -m casulo.compression.cli casv-verify <video.casv>
python -m casulo.compression.cli casv-unpack <video.casv> <frames-restaurados.rgb>
python -m casulo.compression.cli casv-probe <diretorio-append-only>
python -m casulo.compression.cli casv-stream-pack <frames.raw> <video-v02.casv> --width <w> --height <h> --frames <n> --fps-numerator <fps> --evidence-dir <diretorio-novo>
python -m casulo.compression.cli casv-stream-import <fonte.mp4> <video-v02.casv> --frames <n> --max-canonical-mib <limite> --evidence-dir <diretorio-novo>
python -m casulo.compression.cli casv-stream-verify <video-v02.casv>
python -m casulo.compression.cli casv-stream-extract <video-v02.casv> <trecho.raw> --start-frame <i> --frames <n>
python -m casulo.compression.cli casv-tiled-pack <frames.raw> <video-v04.casv> --width <w> --height <h> --frames <n> --fps-numerator <fps> --pixel-format <formato> --tile-width <w> --strip-height <h> --evidence-dir <diretorio-novo>
python -m casulo.compression.cli casv-tiled-import <fonte.mp4> <video-v04.casv> --frames <n> --crop <x> <y> <w> <h> --preserve-source-pixel-format --evidence-dir <diretorio-novo>
python -m casulo.compression.cli casv-tiled-inspect <video-v04.casv>
python -m casulo.compression.cli casv-tiled-verify <video-v04.casv>
python -m casulo.compression.cli casv-tiled-unpack <video-v04.casv> <restaurado.raw>
python -m casulo.compression.cli casv-tiled-probe <diretorio-append-only>
python -m casulo.compression.cli casv-compact-pack <frames.raw> <video-v05.casv> --width <w> --height <h> --frames <n> --fps-numerator <fps> --pixel-format <formato> --tile-width <w> --strip-height <h> --evidence-dir <diretorio-novo>
python -m casulo.compression.cli casv-compact-import <fonte.mp4> <video-v05.casv> --frames <n> --crop <x> <y> <w> <h> --preserve-source-pixel-format --evidence-dir <diretorio-novo>
python -m casulo.compression.cli casv-compact-inspect <video-v05.casv>
python -m casulo.compression.cli casv-compact-verify <video-v05.casv>
python -m casulo.compression.cli casv-compact-unpack <video-v05.casv> <restaurado.raw>
python -m casulo.compression.cli casv-compact-probe <diretorio-append-only>
python -m casulo.compression.cli casv-temporal-pack <frames.raw> <video-v06.casv> --width <w> --height <h> --frames <n> --fps-numerator <fps> --pixel-format <formato> --tile-width <w> --strip-height <h> --keyframe-interval <n> --evidence-dir <diretorio-novo>
python -m casulo.compression.cli casv-temporal-import <fonte.mp4> <video-v06.casv> --frames <n> --crop <x> <y> <w> <h> --preserve-source-pixel-format --tile-width <w> --strip-height <h> --keyframe-interval <n> --evidence-dir <diretorio-novo>
python -m casulo.compression.cli casv-temporal-inspect <video-v06.casv>
python -m casulo.compression.cli casv-temporal-verify <video-v06.casv>
python -m casulo.compression.cli casv-temporal-unpack <video-v06.casv> <restaurado.raw>
python -m casulo.compression.cli casv-temporal-probe <diretorio-append-only>
```

## Claims atuais

Autorizado: existem caminhos estruturais v1 e GOP/NAL v1 executáveis,
causalmente governados por T e reconstruídos por verificadores independentes;
os probes curtos foram bit-exact e tiveram resultado líquido negativo de
compressão. A referência XOR ingênua foi executada e falsificada no corpus
observado; não foi inferida nem substituída por equivalência.

Também autorizado: CASV/0.1–0.6 são formatos próprios executáveis em gates
bounded; CASV/0.5 preservou o hash exato do crop real e seu archive completo
ficou 10,4669% menor que zlib global nesse caso. CASV/0.6 executou predição
temporal exata, mas não selecionou nenhum candidato temporal no clip natural;
o archive venceu zlib e perdeu para zstd, x265 lossless e FFV1. São observações
de uma única instância derivada do vídeo real, não validam compressão
competitiva como classe nem vantagem sobre codecs maduros. O bundle forense
completo foi reportado separadamente.

Não autorizado: compressão próxima de 100% em vídeo natural, vantagem sobre
HEVC/zstd/FFV1/x265/7-Zip, sucesso
em vídeo 8K, sucesso em 100 milhões de registros, economia de datacenter ou
produto comercial pronto. Essas conclusões pertencem às provas LC4 e LC6.
