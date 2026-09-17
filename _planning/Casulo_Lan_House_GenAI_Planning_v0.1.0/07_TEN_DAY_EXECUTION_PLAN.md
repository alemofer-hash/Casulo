# Plano de execução — dez dias

Cada dia termina com um gate binário. Trabalho inconclusivo não é apresentado como concluído. Tempo de download, compilação e benchmark deve ser usado para documentação, testes ou auditoria paralela, sem iniciar outra grande frente.

## Dia 0 — preservação e verdade técnica

Entregas:

- Stage Zero completo;
- mapa de arquivos e componentes;
- baseline de testes;
- distinção implementação/especificação;
- arquitetura canônica escolhida;
- branch `rp0.1-family`.

Gate: repositório recuperável e nenhuma alegação arquitetural sem evidência.

## Dia 1 — esqueleto integrado

- definir processos, protocolos e schemas;
- iniciar Gateway/Core/Memory em modo mock;
- health endpoints;
- logs JSONL com correlation ID;
- configurações sem segredos;
- smoke end-to-end local.

Gate: pergunta mock atravessa cliente -> gateway -> supervisor -> resposta.

## Dia 2 — motor local

- instalar/congelar llama.cpp;
- baixar candidatos 7–9B;
- verificar licença e SHA-256;
- benchmark CPU versus aceleração disponível;
- validar português, JSON e tool calling;
- escolher modelo principal e fallback.

Gate: inferência estável por 120 minutos, apenas em loopback, sem queda abaixo da reserva de RAM/disco.

## Dia 3 — sessões, streaming e fila

- SSE/WebSocket;
- fila persistente;
- uma geração pesada;
- cancelamento;
- timeout e recuperação;
- prioridades owner/family;
- backpressure no cliente.

Gate: três clientes submetem tarefas; execução serial preserva isolamento e cancelamento.

## Dia 4 — agente construtor

- registro de ferramentas;
- JSON Schema;
- read/list/search;
- patch controlado;
- execução de testes;
- receipts e snapshots;
- orçamento de passos;
- aprovação para operações de risco.

Gate: tarefa de código passa por plano, patch, teste e rollback sem shell irrestrito.

## Dia 5 — memória e RAG

- usuários/namespaces;
- SQLite/FTS5;
- embeddings locais;
- ingestão com ACL, origem e hash;
- citações internas;
- exclusão/reindexação verificável;
- proteção contra cruzamento de usuários.

Gate: testes adversariais provam ausência de vazamento entre dois usuários.

## Dia 6 — voz

- auditar integração existente;
- preservar `small-q5_1` e perfil rápido `base-q5_1`;
- estabilizar TTS Maria/PCM16;
- streaming progressivo;
- VAD;
- resolver smoke estrito de barge-in;
- descarte de áudio bruto.

Gate: dez conversas completas, três interrupções e zero arquivo PCM residual inesperado.

## Dia 7 — PWA e dispositivos

- UI mobile-first;
- HTTPS local;
- instalação PWA;
- login;
- pareamento one-time;
- token por dispositivo;
- revogação imediata;
- firewall de sub-rede;
- prova de recusa a dispositivo não pareado.

Gate: dois dispositivos autorizados entram; terceiro não autorizado é recusado.

## Dia 8 — competência de programação

- indexação incremental de repositório;
- mapa de símbolos/dependências;
- seleção de contexto;
- patch multi-arquivo;
- lint/test/build;
- revisão independente da alteração;
- limites de repetição;
- comparação de candidatos por verificadores.

Gate: conjunto fixo de tarefas reais com métricas de êxito e nenhuma regressão oculta.

## Dia 9 — operação doméstica

- inicialização automática controlada;
- estados offline/online;
- dashboard de saúde;
- backup/restore;
- rotação de logs;
- limites de disco;
- recuperação de crash;
- manual owner/family;
- SBOM e licenças.

Gate: reinício frio recupera serviço e dados consistentes sem intervenção de desenvolvimento.

## Dia 10 — prova de independência

- bloquear internet;
- executar matriz completa;
- confirmar listeners;
- medir RAM, disco, latência, temperaturas;
- inspecionar tráfego;
- testar voz, RAG, código, rollback e revogação;
- empacotar release e hashes;
- registrar limitações sem maquiagem.

Gate final: `CASULO_FAMILY_RP0.1_OFFLINE_ACCEPTED` ou relatório objetivo de bloqueio.

