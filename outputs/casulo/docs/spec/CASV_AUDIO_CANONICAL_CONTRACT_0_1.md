# Contrato de áudio canônico CASV/0.1

Estado: `CONTRACT_IMPLEMENTED_CONTAINER_INTEGRATION_PENDING`

## Fronteira de identidade

Este contrato define a identidade de **amostras PCM decodificadas**. Ele não
promete reconstruir bytes AAC, Opus, FLAC, WAV, MP4 ou de qualquer outro
container de origem:

```text
decode canônico registrado da fonte -> PCM X
CASV futuro -> decoder independente -> PCM X'
SHA-256(X) == SHA-256(X')
```

A versão, o hash e os argumentos do decoder fazem parte da proveniência. Uma
conversão de sample rate, mixagem, normalização, dithering ou mudança de ordem
dos canais cria outra derivação e não pode ser rotulada como preservação do
fluxo decodificado nativo.

CASV/0.2 continua sendo exclusivamente vídeo. Nenhum áudio está armazenado no
container atual e `audio_included=false` permanece obrigatório. A primeira
versão audiovisual exigirá novo número de formato e decoder correspondente;
este documento não antecipa esse gate.

## Grade PCM

`CanonicalAudioSpec` em `src/casulo/compression/casv_audio.py` declara:

| Campo | Significado |
|---|---|
| `sample_format` | representação escalar explícita |
| `sample_rate` | amostras por segundo e por canal |
| `channel_labels` | ordem canônica e não ambígua dos canais |
| `samples_per_channel` | comprimento exato de cada canal |
| `start_time_numerator/denominator` | origem racional na timeline comum |
| `layout` | sempre `INTERLEAVED_DECLARED_CHANNEL_ORDER` |
| `canonical_bytes` | produto exato de amostras, canais e largura escalar |

Formatos aceitos pelo contrato:

| Identificador | Largura | Interpretação |
|---|---:|---|
| `PCM_U8` | 1 byte | inteiro sem sinal |
| `PCM_S16LE` | 2 bytes | inteiro com sinal, little-endian |
| `PCM_S32LE` | 4 bytes | inteiro com sinal, little-endian |
| `PCM_S64LE` | 8 bytes | inteiro com sinal, little-endian |
| `PCM_F32LE` | 4 bytes | IEEE-754 binary32, little-endian |
| `PCM_F64LE` | 8 bytes | IEEE-754 binary64, little-endian |

O formato do sample não é escolhido por conveniência de compressão. Uma rota
de importação futura precisa provar que o mapeamento preserva o valor de cada
sample. Formatos desconhecidos falham fechados.

## Timeline e sincronização

O sample de índice `i` começa em:

```text
start_time_numerator / start_time_denominator + i / sample_rate
```

Vídeo e áudio mantêm relógios racionais separados e uma origem comum. O player
não pode inferir sincronia apenas por duração aproximada. Gaps, priming,
padding, edit lists e timestamps negativos precisam ser declarados ou a
importação audiovisual deve ser recusada.

## Limites e validação

O contrato falha antes de qualquer alocação de payload quando encontra:

- formato desconhecido;
- sample rate fora de `1..768000`;
- zero canais ou mais de 64;
- labels vazios, duplicados, não ASCII ou contendo pontuação de controle;
- contagem negativa ou representação maior que `2^64-1` bytes;
- denominador temporal não positivo;
- payload menor ou maior que a grade declarada.

O contrato não preenche, trunca nem deduz samples ausentes.

## Autoridade T futura

Uma integração audiovisual só poderá ser chamada de causalmente governada por
T quando T decidir, antes do commit:

1. quais tracks entram na identidade da mídia;
2. qual mapeamento PCM é admissível sem perda;
3. como gaps e origem temporal são tratados;
4. qual primitive reversível armazena cada segmento;
5. se reconstrução, sincronia e custo autorizam a publicação.

Hoje essas decisões ainda não atravessam o pipeline T. O contrato de dados está
implementado e testado; encode, segmentação, mux, seek e playback sincronizado
permanecem pendentes.

## Evidência de engenharia

Os testes cobrem contabilidade PCM interleaved, formatos e taxas inválidas,
canais duplicados, label hostil, tempo inválido e tamanho de payload inexato.
Eles provam a validade local do contrato, não reprodução audiovisual.
