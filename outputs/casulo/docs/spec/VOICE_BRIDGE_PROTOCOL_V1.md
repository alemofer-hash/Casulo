# Voice Bridge Protocol V1

Estado: contrato executável; engine/modelo ainda não adotados.

O processo do produto e o adapter ASR comunicam por JSON Lines UTF-8 em pipes,
sem shell. Cada linha tem no máximo 256 KiB.

## Comandos

Todos usam `schema=casulo-asr-command/1.0`:

- `audio`: `sample_rate`, `channels=1` e `pcm_s16le_b64`;
- `finalize`: conclui a fala atual;
- `reset`: descarta estado da fala;
- `shutdown`: termina de forma ordenada.

## Eventos

O bridge responde com `schema=casulo-asr-event/1.0`, `transcript_id`, `text`,
`locale=pt-BR`, `final` booleano e `confidence` nulo ou entre 0 e 1.

O adapter rejeita schema, locale, confiança ou tamanho inválidos. Um evento
final antes de `finalize` é falha de contrato. O processo deve terminar somente
após drenar sua saída; cancelamento e timeout encerram o boundary sem executar
comando textual via shell.

O protocolo não concede capabilities e não implica adoção de `whisper.cpp`.
Qualquer engine local compatível pode ficar atrás do mesmo boundary. O binário,
modelo, licença, hash e card precisam passar pelo registry antes de uso.
