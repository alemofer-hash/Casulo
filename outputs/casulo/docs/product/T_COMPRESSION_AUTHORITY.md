# Autoridade causal de T na compressão estrutural

Data: 2026-09-10  
Estado: `T_COMPRESSION_CAUSAL_AUTHORITY_GOP_PROBE_PASS`

## Superfície governada

T governa duas decisões anteriores à publicação de cada segmento:

1. `plan`: quais primitives reversíveis podem ser executadas;
2. `decide`: qual payload comprovadamente reversível será persistido.

O caminho é:

```text
examples/t-v2/compression_structural.t
-> V2Parser
-> V2Analyzer
-> lower_module (typed IR)
-> TcapV2Builder (grafo + TCAP)
-> casulo-t-runtime.exe (Rust)
-> plan receipt
-> execução somente da família autorizada
-> decide receipt
-> payload content-addressed
```

O encoder não tem fallback que escolha outra política. Resultado `error`,
transform desconhecido, candidato ausente, receipt inválido ou TCAP inválido
encerra a operação antes da publicação.

## Inputs observados por T

O planejamento recebe tipo estrutural, tamanho e classe de entropia. O
julgamento recebe hashes previamente coerentes, prova local de round-trip,
presença de cada candidato e tamanho real de cada payload. A classe de entropia
é uma observação; ela não é tratada como energia, compressão ou prova de
reversibilidade.

As famílias v1 são:

| Resultado T | Primitives permitidas |
|---|---|
| `RAW_ONLY` | `raw` |
| `RAW_ZLIB_SHUFFLE` | `raw`, `zlib`, `shuffle4-zlib` |
| `ALL` | todas as cinco transforms v1 |

Headers sempre recebem `RAW_ONLY`. Payload HEVC com entropia igual ou superior
a 7,5 bits/byte recebe `RAW_ZLIB_SHUFFLE`; metadados recebem `ALL`. O limiar
está no programa T, não duplicado como decisão no encoder.

## Receipts verificáveis

Cada segmento produz exatamente dois receipts do runtime produtivo:

```text
plan_i -> decide_i -> plan_i+1
```

O archive contém:

- a source T;
- todas as seções do TCAP;
- receipts em hash chain;
- inputs e observables canônicos de cada chamada;
- a ligação do segmento ao receipt `decide` correspondente.

O decoder independente recalcula:

- SHA-256 da source T;
- identidade do TCAP e suas seções;
- hashes de input e output dos receipts;
- cadeia e ordem `plan/decide`;
- correspondência entre família planejada e candidatos realmente presentes;
- correspondência entre tamanhos fornecidos e `candidate_bytes`;
- correspondência entre o resultado T e o transform persistido.

Assim, o receipt não é apenas produzido depois do fato: o observable T está
preservado e pode ser confrontado com o trabalho e payload publicados.

## Mutação causal executada

Controle: `examples/t-v2/compression_structural_force_raw.t`.

Foi alterada somente a política T. Mesma fonte derivada, encoder, runtime,
chunking e decoder foram mantidos. No probe final:

| Evidência | Padrão | Force raw | Mudou? |
|---|---:|---:|---|
| source T SHA-256 | `c1b32f...5049e` | distinto | sim |
| TCAP SHA-256 | `fd2435...c1641` | distinto | sim |
| primitives invocadas | 19 | 7 | sim |
| bytes de candidatos produzidos | 12.604.330 | 4.204.386 | sim |
| seleção final | 4 raw + 3 shuffle | 7 raw | sim |
| archive final | 4.280.913 bytes | distinto | sim |
| reconstrução independente | PASS | PASS | não deve mudar |

Portanto, a alteração em T mudou trabalho executado, trace e artefato, enquanto
preservou os bytes reconstruídos. Esse é o escopo exato da causalidade
demonstrada.

## Fronteiras estrangeiras

T não implementa SHA-256, DEFLATE nem os loops de transformação. As primitives
são Python/CPython zlib e estão manifestadas com ABI, versão, efeitos e
`decision_owner=T`. T decide se são invocadas e qual resultado é aceito.

Isso autoriza: “T exerceu autoridade causal sobre planejamento e seleção de
transforms no probe”. Não autoriza: “T é o codec”, “T comprime HEVC sozinha” ou
“T produz ganho de compressão próximo de 100%”.

## Limitações abertas

- A observação de entropia ainda é executada em Python e percorre o segmento.
- Os prepasses delta/xor/shuffle ainda são Python escalares.
- A política v1 minimiza payload local, não custo total global do archive.
- Não há ainda dictionary learning, modelagem inter-frame bit-exact, parsing
  completo de slice headers, CABAC ou transformação de GOP.
- O probe é curto e derivado; a causalidade está aprovada, o resultado final do
  arquivo de 18,38 GB não foi medido pelo caminho estrutural.

Essas limitações são de desempenho e poder de modelagem, não lacunas ocultas na
cadeia causal já exercida.

## Extensão HEVC GOP/NAL

A fonte `examples/t-v2/compression_hevc_gop.t` acrescenta uma superfície
independente, compilada pelo mesmo pipeline geral. Por corpo NAL, T executa:

```text
plan -> primitives autorizadas -> decide -> payload
```

Ao final do archive, T recebe evidência de reconstrução, partição e tamanho e
executa `judge`. O encoder não publica alegação de ganho quando `judge` retorna
`REJECT`.

No probe real final, a política padrão autorizou nove invocações e selecionou
três corpos raw e um zlib. A mutação `compression_hevc_gop_force_raw.t` alterou
somente T, reduziu o trabalho a quatro invocações e persistiu quatro corpos raw.
Source T, IR, TCAP, receipts, trace e archive mudaram; o corpus reconstruído
permaneceu idêntico.

O transform `xor-reference-prefix-zlib` foi executado de verdade sobre 1 MiB do
segundo corpo VCL contra o primeiro. Ele produziu 29.128.928 bytes para uma
entrada de 29.128.594 bytes e perdeu. Zlib isolado produziu 29.069.645 bytes e
foi selecionado. Após metadados, o archive ainda expandiu 4.016 bytes; `judge`
recusou o resultado.

Essa extensão autoriza dizer que T governou causalmente candidate family,
seleção e aceitação de custo no probe GOP/NAL. Ela não autoriza dizer que T
implementa zlib/XOR, que houve compressão líquida ou que o modelo inter-frame
HEVC foi resolvido.

## Extensão CASV/0.1

`examples/t-v2/compression_casv.t` governa duas decisões do novo formato
visual próprio:

1. seleção pré-commit entre `GENERATIVE_EXACT`, `CANONICAL_ZLIB` e
   `CANONICAL_RAW`;
2. julgamento pós-decode do tamanho integral como `ACCEPT` ou `REJECT`.

A política atravessa frontend, semântica, IR, grafo, TCAP e runtime Rust. No
probe estruturado, escolheu `GENERATIVE_EXACT`; a mutação exclusivamente T
`compression_casv_force_raw.t` escolheu `CANONICAL_RAW`. Os arquivos e TCAPs
mudaram, mas o SHA-256 dos quadros reconstruídos permaneceu igual.

TCAP padrão observado no probe:

```text
34f2d8df9d663089ba981550073c79480228bd1f6ed0a153d00a7905081d1a24
```

Esse hash permanece como evidência histórica do CV0. No CV1.1, o contrato
ganhou `generative_candidate_available`: T passou a impedir que um renderer
inexistente fosse tratado como candidato válido para `YUV444P10LE`. O TCAP
observado no probe nativo de 10 bits foi:

```text
05f5fb569fe3f1f393015e3dabaa5c4af8ab2e0ed33d664ec4192b6280f7b865
```

Com a flag falsa, T escolheu `CANONICAL_ZLIB` antes do commit. O caminho não
atribuiu ao modelo RGB8 uma compressão que ele não executou.

O proposer geométrico, o tracking, os materiais e o renderer ainda são
implementados em Python e constam em `not_yet_governed_by_t`. Portanto, o gate
atual é causal apenas para seleção e julgamento; T ainda não é a arquiteta
integral da representação visual.

## Extensão CASV/0.2 segmentada

No container streaming, cada bloco apresenta a T `segment_index`, SHA-256
canônico, disponibilidade do candidato e custos antes de qualquer byte ser
comitado. IDs de chamada e receipts são distintos e encadeados; o manifesto
associa cada segmento ao receipt que escolheu raw ou zlib. Um julgamento
separado ocorre somente após o decoder independente fechar o hash integral.

No probe de engenharia de 2026-09-10, ocorreram 27 decisões de armazenamento e
um julgamento. Treze blocos escolheram raw e quatorze zlib. Hashes correntes:

```text
T source  69f36035a710f9546c85d567de86cd4285c4c30543727654f98f2754dad5335f
T IR      b76c964d0f7978436fc65709641e251777a7c47d7a8f28715c747afbb7ae84b3
TCAP      8fdcb3fb294a4563efb639327dda9e8b2dba33519211f70a15ace161108f91e0
```

Isso prova autoridade causal de seleção por segmento. Não prova que T criou o
codec: zlib e cópia raw continuam primitives Python/stdlib, e o candidato
generativo do 0.2 permanece explicitamente indisponível.

## Adapter direto FFmpeg/CASV

CV1.3 não amplia artificialmente a autoridade de T. O FFmpeg continua sendo a
primitive estrangeira que decodifica o bitstream; Python congela e valida o
plano do processo e transporta os bytes. T recebe cada segmento somente depois
de ele existir e governa sua seleção raw/zlib antes do commit.

No probe real, sete segmentos distintos produziram sete receipts de seleção.
O hash canônico `eb1c094a...bc3aa8` coincidiu com a rota bounded anterior, e o
decoder independente fechou o mesmo hash. T não escolheu crop, pixel format,
FFmpeg, segmentação nem áudio. Essas superfícies continuam estrangeiras ou
ausentes e não entram no score de autoridade demonstrado.

O gate novo é de integridade transacional: mesmo que FFmpeg produza a
quantidade esperada de bytes, exit code não zero impede a publicação. Isso
protege a evidência consumida por T; não transforma T no decoder.

## Extensão CASV/0.3 com programa causal

CASV/0.3 apresenta a T três candidatos efetivamente construídos por segmento:

```text
GENERATIVE_EXACT = CVG3(base + dinâmica + residual XOR)
CANONICAL_ZLIB   = zlib dos mesmos bytes canônicos
CANONICAL_RAW    = os mesmos bytes sem transformação
```

O encoder prova localmente o fechamento do candidato causal antes da chamada.
T compara os comprimentos observados e sua resposta define quais bytes são
gravados. O decoder independente interpreta o programa sem runtime T e valida
SHA-256 por segmento e integral.

O probe selado executou uma mutação causal: com a mesma fonte, encoder e
primitives, `compression_casv.t` escolheu três programas de 150 bytes e
`compression_casv_force_raw.t` escolheu três blocos raw de 62.208 bytes. Os
TCAPs e receipts diferiram, mas o SHA-256 reconstruído foi idêntico.

No recorte natural de oito quadros, T recebeu os custos 357.828 bytes para o
programa, 363.549 para zlib e 1.769.472 para raw, escolhendo o programa antes do
commit. Isso é autoridade causal sobre seleção. O proposer não encontrou
tracks e só 2.324 de 294.912 pixels coincidiram integralmente com a base; a
economia veio do residual transformado, não de compreensão semântica rica.

Os hashes da policy padrão continuam:

```text
T source  69f36035a710f9546c85d567de86cd4285c4c30543727654f98f2754dad5335f
T IR      b76c964d0f7978436fc65709641e251777a7c47d7a8f28715c747afbb7ae84b3
TCAP      8fdcb3fb294a4563efb639327dda9e8b2dba33519211f70a15ace161108f91e0
```

As superfícies `scene_proposal`, `object_tracking`, `material_inference` e
`renderer_primitive_implementation` permanecem fora da autoridade T. A política
também não escolhe hoje crop, layout de tiles, tamanho de grupo, pixel format ou
adapter FFmpeg. Nenhuma dessas decisões entra artificialmente no score causal.

## Extensão CASV/0.4 por tile

CASV/0.4 apresenta a T quatro candidatos já construídos e reconstruídos
localmente para cada tile:

```text
DC_XOR_ZLIB
PAETH_ZLIB
CANONICAL_ZLIB
CANONICAL_RAW
```

A policy `compression_casv_tile.t` escolhe o menor custo exato incluindo a
entrada binária de 16 bytes do tile. A escolha é consumida antes do commit da
faixa. A mutação `compression_casv_tile_force_raw.t` altera somente T e força
raw; writer, primitives e decoder ficam inalterados.

O runtime Rust passou a aceitar batches. Batching significa somente uma
invocação física por faixa: cada tile recebe máquina T nova, input/output hash,
receipt e elo próprio. No crop real foram 72 decisões semânticas, 18 processos
e 72 receipts de seleção, seguidos de um receipt de julgamento.

Hashes da policy padrão executada no probe real:

```text
T source  d3b9389aa427fbda86e7ffe2be027ef8494fd63e39a73b1b145b6b2fddbb47bb
T IR      9ad1368a07a44b64475facb8d396e96b4c9bf5361c93d04aa62d9780585efd93
TCAP      de04888911a40a4855f8d47b6920cd654cff149aa13c2cc495ed9f036d87e83b
```

O gate causal passou: policy T mutada mudou armazenamento, TCAP e receipts sem
alterar a mídia reconstruída. O gate econômico não passou. No crop real, o
record stream escolhido ficou 8.720 bytes menor que zlib global, mas o archive
final ficou 7.607 bytes maior por causa do manifesto.

O `cost_verdict=ACCEPT` desse artifact compara archive a raw canônico. Ele não
significa vantagem contra zlib. O relatório atual separa explicitamente custo
de payload, record stream e archive para eliminar essa ambiguidade.

No estágio 0.4, T ainda não escolhia canonicalização, pixel format, crop,
geometria de tiles, preditor temporal, zlib, áudio ou a política global que
minimizasse o container inteiro. O primeiro desses avanços — julgar o custo
total do índice compacto antes da publicação — foi implementado no 0.5 abaixo.

## Extensão CASV/0.5 e juízo integral

`compression_casv_compact.t` preserva a seleção causal por tile e acrescenta
`reference_zlib_bytes` ao contrato de julgamento. O fluxo efetivamente
executado é:

```text
candidatos exatos
→ decisão T por tile
→ escrita do candidato completo
→ reconstrução por decoder independente
→ contagem de archive e zlib global
→ juízo T
→ publicação atômica ou preservação como rejeitado
```

O juízo retorna `ACCEPT_BEATS_REFERENCE`, `ACCEPT_RAW_ONLY` ou `REJECT`. O
writer consome o retorno: `REJECT` impede a criação do caminho público do
archive. A mutação `compression_casv_compact_force_raw.t` mudou somente a
policy/TCAP, forçou raw e impediu publicação nos fixtures medidos. Portanto o
resultado T não é decorativo nem receipt posterior.

Hashes da policy padrão na evidência real final:

```text
T source  705922fadaadb54e283e31ffa05c20b22a0e1f75eeca8399f37378c9cfb7e022
T IR      3f0cf50db21be0a2a49eb3f24cf6be1910c8a90266e4603bec022601be591353
TCAP      4b1bfb803e58749502a94408d2c9608b9c46ebf4ee1d493216eb7fd4c2914b0c
```

No recorte real, T escolheu 65 Paeth, 3 DC/XOR e 4 zlib, totalizando 72
receipts de storage e um de julgamento. O archive de 84.958 bytes foi menor
que a referência zlib de 94.890 e foi publicado. O mesmo hash canônico foi
reconstruído independentemente.

Essa autoridade ainda é parcial sobre o sistema total. Python constrói os
candidatos, zlib executa DEFLATE e a geometria é fornecida pelo chamador. T não
escolhe o decoder FFmpeg, crop, pixel format, tile/strip, predição temporal ou
primitive matemática. A alegação autorizada é autoridade causal sobre seleção
dos quatro candidatos e aceitação econômica final do archive CASV/0.5.

## Extensão CASV/0.6 e candidatos temporais

`compression_casv_temporal.t` amplia a superfície de seleção com dois
candidatos reversíveis que referenciam o tile homólogo do quadro anterior:

```text
TEMPORAL_XOR_ZLIB
TEMPORAL_SUB_ZLIB
```

O encoder materializa e reconstrói cada candidato antes da decisão. T recebe a
disponibilidade e o SHA-256 da referência, a prova de round-trip e o custo
integral de cada alternativa. Em keyframes a referência é estruturalmente
indisponível; o decoder independente também proíbe qualquer modo temporal
nesses quadros.

A mutação `compression_casv_temporal_force_spatial.t` altera somente T e veta
os dois modos temporais. No controle sintético, a policy normal selecionou oito
tiles temporais e produziu archive de 37.620 bytes; a mutação mudou source,
IR, TCAP, trace e receipts, produziu 111.076 bytes e recebeu `REJECT`. Ambas as
rotas reconstruíram exatamente a mídia. Isso demonstra autoridade causal sobre
a nova escolha, não eficácia em vídeo natural.

Hashes da policy padrão na evidência natural final:

```text
T source  6705ab456d76ac6c359d0b634e0a0b45c196785a18970f40c57dcaa517903095
T IR      4a2c170f118f13aaf86df09c0edb80c1b95743b3888bfdad7020474d160110d7
TCAP      d869147fff02124069d64a223da5c6a5c4818c80276f8af1d58522313fe29a94
```

No clip natural, T avaliou 252 oportunidades temporais e escolheu zero: os
modos espaciais somaram 280.489 bytes, contra 375.957 de SUB e 412.207 de XOR.
O archive CASV/0.6 ficou 66,9971% maior que FFV1. A decisão correta de não usar
um candidato ruim é evidência de autoridade, mas não de vantagem de
compressão.

T continua sem escolher decodificação da fonte, canonicalização, crop, pixel
format, geometria, algoritmo de busca de movimento, zlib ou implementação das
primitives. A autoridade demonstrada em 0.6 é somente seleção causal entre
candidatos exatos apresentados e julgamento de publicação contra zlib global.
