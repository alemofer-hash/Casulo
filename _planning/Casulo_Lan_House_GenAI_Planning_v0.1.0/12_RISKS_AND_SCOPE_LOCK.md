# Riscos e bloqueio de escopo

## Riscos principais

| Risco | Impacto | Controle |
|---|---|---|
| conteúdo consolidado incompleto | alto | auditoria Stage Zero |
| documentação confundida com código | alto | evidência por arquivo/teste |
| 16 GB insuficientes para contexto/modelo | alto | 7–9B Q4, fila, 8k |
| SSD enche com WSL/caches | alto | gate de 30 GB e orçamento |
| throttling do laptop | alto | HWiNFO, resfriamento, soak test |
| PWA sem HTTPS perde microfone | alto | CA/certificado local |
| serviço interno exposto | crítico | loopback + teste de listeners |
| vazamento entre familiares | crítico | namespace/ACL/teste adversarial |
| agente destrói arquivos | crítico | patch, snapshot, confirmação |
| modelo insiste no mesmo erro | médio | verificadores, orçamento, diversidade |
| expansão de escopo | alto | constituição e gates diários |

## Congelamento do RP0.1

Aceitar somente trabalho que contribua diretamente para:

- chat;
- voz;
- PWA LAN;
- pareamento;
- memória isolada;
- RAG;
- programação com testes;
- segurança, rollback e operação offline.

Todo recurso novo deve responder:

1. é necessário para um critério de pronto?
2. pode ser concluído/testado dentro do gate atual?
3. cabe no orçamento de RAM/disco?
4. introduz serviço externo obrigatório?

Qualquer `não` ou incerteza forte envia o recurso ao backlog pós-RP0.1.

## Honestidade de resultado

O release pode ser útil sem ser equivalente ao Codex. Registrar:

- tarefas em que supera por persistência/tempo;
- tarefas em que falha por inteligência/contexto;
- velocidade real;
- qualidade da voz;
- limites de concorrência;
- riscos de segurança ainda abertos.

