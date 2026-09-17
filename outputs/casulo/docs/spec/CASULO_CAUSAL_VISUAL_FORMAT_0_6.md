# CASV/0.6 — predição temporal reversível

Status: implementação experimental, `EXACT_MEDIA`, vídeo sem áudio.

## Finalidade

CASV/0.6 acrescenta referências temporais ao índice binário compacto 0.5 sem
encapsular MP4, HEVC ou outro bitstream de vídeo. O formato preserva a sequência
canônica de amostras decodificadas:

```text
decode canônico da fonte -> X
CASV/0.6 -> decoder independente -> X'
SHA-256(X) == SHA-256(X')
```

Isso não preserva os bytes do contêiner de origem. Áudio não faz parte desta
versão.

## Organização binária

Todos os inteiros são big-endian. O overhead estrutural é:

```text
160 + 44 * record_count + 5 * tile_count
```

| Estrutura | Formato | Bytes |
|---|---|---:|
| magic | `CASV 00 06 0d 0a` | 8 |
| header | `>BBH8IQ32s` | 76 |
| record header | `>4sII32s` | 44 por record |
| tile entry | `>BI` | 5 por tile |
| footer | `>8sI32s32s` | 76 |

O header declara formato de pixel, dimensões, quadros, frame rate, tile,
faixa, intervalo de keyframe, total canônico e SHA-256. A geometria completa é
derivada desses campos; não existe manifesto JSON dentro do bitstream.

Cada record corresponde, em ordem canônica, a uma faixa de um plano de um
quadro. Seu header fixa índice, comprimento agregado do payload e SHA-256 da
faixa reconstruída. A tabela informa modo e comprimento de cada tile. O footer
vincula quantidade de decisões T, cabeça da cadeia de receipts e hash de todo o
conteúdo anterior ao footer.

## Base, dinâmica e residual

Em quadros que não são keyframes, a base temporal de um tile é o tile homólogo
do quadro imediatamente anterior: mesmos plano, coordenada vertical,
coordenada horizontal, dimensões e precisão.

Os dois programas temporais são:

```text
TEMPORAL_XOR_ZLIB = zlib(current XOR previous)
current           = residual XOR previous

TEMPORAL_SUB_ZLIB = zlib((current - previous) mod 256)
current           = (residual + previous) mod 256
```

Os modos espaciais continuam disponíveis:

- `CANONICAL_RAW`;
- `CANONICAL_ZLIB`;
- `DC_XOR_ZLIB`;
- `PAETH_ZLIB`.

Todo candidato é reconstruído e comparado ao tile canônico antes de chegar à
autoridade T. O valor persistido é a alternativa exata de menor custo escolhida
pela política T. Empate é resolvido pela ordem explícita da política.

## Keyframes

Um quadro é keyframe quando:

```text
frame_index % keyframe_interval == 0
```

Modos temporais são estruturalmente proibidos nesses quadros. O intervalo fica
no header, deve estar entre 1 e 1.024 e é validado pelo decoder antes de ler os
payloads. Referências são implícitas e nunca podem apontar para futuro, outro
plano ou outra geometria.

## Memória e disco temporário

Encoder e decoder processam uma faixa por vez. Para permitir referência entre
quadros sem manter um quadro 8K inteiro em RAM, ambos usam um arquivo temporário
anônimo e rotativo contendo no máximo o quadro anterior. Assim:

- memória explícita é limitada às faixas, tiles e candidatos ativos;
- disco temporário máximo da referência é um quadro canônico;
- o arquivo temporário não integra o `.casv` nem sobrevive ao processo normal;
- não há alegação de pico RSS medido até instrumentação específica.

## Autoridade causal T

A política `compression.casv_temporal` recebe, antes do commit de cada tile:

- coordenadas e SHA-256 canônico;
- disponibilidade e SHA-256 da referência;
- prova de reconstrução exata;
- proibição de bitstream estrangeiro;
- custo integral de cada candidato, incluindo sua entrada de tabela.

Ela escolhe o modo efetivamente gravado. Uma mutação somente em T que proíbe
modos temporais muda TCAP, trace, receipts e arquivo resultante. Depois da
reconstrução independente, T também decide se o candidato pode ser publicado:

```text
archive < zlib global -> ACCEPT_BEATS_REFERENCE
archive < raw         -> ACCEPT_RAW_ONLY
senão                 -> REJECT
```

`REJECT` preserva o candidato no diretório de evidência, mas não publica o
caminho solicitado.

## Decoder independente

`independent_casv_temporal_stream.py` usa somente a biblioteca padrão e não
importa encoder, IR, policy ou autoridade T. Ele valida limites, ordem,
keyframes, modos, comprimentos, hashes de records, footer, conteúdo e mídia
canônica. A publicação de unpack é atômica.

## Fronteira de alegação

O formato prova um caminho temporal reversível e auditável. Não prova que a
predição homóloga é útil em vídeo natural, que o CASV vence codecs maduros, que
um vídeo 8K integral foi codificado ou que compressão próxima de 100% é
possível. Essas questões dependem de campanhas pré-congeladas e seus resultados
negativos permanecem evidência válida.
