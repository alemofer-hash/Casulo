# CASV/0.7 — compensação de movimento inteira e reversível

Status: implementação experimental exata; ramo competitivo natural rejeitado.

## Contrato

CASV/0.7 estende o CASV/0.6 com uma busca inteira, bounded e causal no quadro
imediatamente anterior. A reconstrução continua sendo da mídia canônica, não do
container MP4/HEVC original:

```text
fonte selada -> amostras canônicas X
CASV/0.7 -> decoder independente -> X'
SHA-256(X) == SHA-256(X')
```

Nenhum bitstream estrangeiro é embutido. Áudio permanece fora do formato.

## Organização binária

Todos os inteiros estruturais são big-endian. O overhead sem payload é:

```text
164 + 44 * record_count + 5 * tile_count
```

| Estrutura | Formato | Bytes |
|---|---|---:|
| magic | `CASV 00 07 0d 0a` | 8 |
| header | `>BBH9IQ32s` | 80 |
| record header | `>4sII32s` | 44 por record |
| tile entry | `>BI` | 5 por tile |
| footer | `>8sI32s32s` | 76 |

O nono inteiro de 32 bits do header declara `motion_radius`. O decoder recusa
raio zero, raio acima de 32, geometria impossível, referência preditiva em
keyframe e vetor fora do quadro anterior.

## Base, dinâmica e residual

Para um tile corrente em `(x, y)`, o vetor `(dx, dy)` referencia o retângulo de
mesma geometria em `(x + dx, y + dy)` no mesmo plano do quadro anterior. O
vetor `(0, 0)` não é duplicado: ele pertence aos modos temporais homólogos de
0.6.

Dois modos foram acrescentados:

```text
MOTION_XOR_ZLIB = int8(dx) || int8(dy) || zlib(current XOR reference)
MOTION_SUB_ZLIB = int8(dx) || int8(dy) || zlib((current-reference) mod 256)
```

Na reconstrução, XOR ou soma modular recompõem cada byte. Os dois bytes do
vetor fazem parte do payload e, portanto, do custo entregue a T. Não existe
side channel de movimento gratuito.

## Busca congelada

A campanha natural fixou antes da implementação:

- raio de 8 pixels;
- SAD consciente de sample, amostrado a cada quatro pixels;
- até quatro vetores finalistas por família residual;
- ordenação de busca por SAD, distância Manhattan, `dy` e `dx`;
- escolha final por comprimento integral do payload e, em empate, pela mesma
  ordem determinística;
- tiles de 40 pixels, faixas de 48 linhas e keyframe a cada oito quadros.

Para `YUV444P10LE`, o SAD interpreta cada sample little-endian de 16 bits; o
residual exato permanece bytewise. Para RGB8, o SAD soma as três componentes.

## Autoridade T

`compression.casv_motion` recebe antes do commit:

- identidade do tile e seu SHA-256;
- disponibilidade/hash da referência homóloga;
- disponibilidade, quantidade e raio dos vetores;
- vetor e hash de referência de cada vencedor motion;
- custo integral dos oito modos;
- prova de reconstrução exata e ausência de bitstream estrangeiro.

T escolhe o payload efetivamente gravado entre raw, zlib, DC/XOR, Paeth,
temporal XOR/SUB e motion XOR/SUB. Python não substitui a decisão. Uma mutação
somente T que proíbe motion mudou TCAP, trace e tamanho no probe sintético.

## Decoder independente

`independent_casv_motion_stream.py` usa somente a biblioteca padrão. Ele não
importa encoder, IR, autoridade ou política T. Antes de reconstruir, valida:

- header, record order, tabela, comprimentos e footer;
- keyframes, raio, vetores e retângulos de referência;
- hashes de records, conteúdo do archive e mídia final;
- contagem e cabeça da cadeia de decisões T.

Encoder e decoder mantêm uma faixa ativa em memória e um quadro anterior em
arquivo temporário anônimo. Não há alegação de RSS medido.

## Resultado e fronteira

O formato passou o gate de engenharia e round-trip. Nos três holdouts naturais
pré-registrados, porém, T selecionou zero candidatos motion e a razão geométrica
CASV/menor baseline exato foi 1,745048. O protocolo determinou
`REJECT_MOTION_BRANCH_AND_ADVANCE_TO_CAUSAL_VISUAL_GRAMMAR`.

Logo, 0.7 prova que o mecanismo existe e é causal, não que seja competitivo.
Não há prova de vídeo 8K integral, áudio, vantagem geral, compressão próxima de
100% ou superioridade sobre codecs maduros.
