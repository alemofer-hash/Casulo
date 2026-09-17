# Arquitetura-alvo

## Topologia

```text
Dispositivo aprovado
  -> HTTPS 8443
  -> Casulo Gateway
       -> autenticação + device registry
       -> rate limit + fila + cancelamento
       -> session/memory policy
       -> agent supervisor
            -> llama-server 127.0.0.1:8081
            -> ASR 127.0.0.1:8082
            -> TTS 127.0.0.1:8083
            -> RAG/memory local
            -> tool workers sem privilégio
```

## Componentes

### Casulo Gateway

- único listener da LAN;
- TLS, autenticação e autorização;
- WebSocket ou SSE para streaming;
- PWA e API versionada;
- fila com uma geração pesada por vez;
- cancelamento e timeout;
- limites por usuário/dispositivo;
- nenhum acesso direto do cliente a ferramentas internas.

### Model Router

- escolhe perfil geral, código ou fallback;
- mantém somente um modelo grande residente;
- descarrega e troca modelo de forma explícita;
- registra modelo, quantização, parâmetros e hash por resposta;
- recusa contexto incompatível com orçamento de memória.

### Agent Supervisor

- plano estruturado;
- chamadas de ferramenta por JSON Schema;
- orçamento de passos;
- confirmação por classe de risco;
- execução, observação e revisão;
- receipts, diffs e rollback.

### Memory Service

- SQLite/FTS5 como base inicial;
- namespaces separados por usuário;
- chunks com hash, origem, ACL e versão;
- embeddings locais;
- nenhum documento entra no índice sem autorização.

### Voice Duplex

- VAD e ASR locais;
- texto passa pelas mesmas políticas do chat;
- TTS local e streaming progressivo;
- barge-in cancela geração/reprodução de modo consistente;
- áudio bruto descartado após processamento por padrão.

### Tool Workers

- executam como usuário sem privilégio;
- raiz limitada ao workspace autorizado;
- comandos allowlisted ou confirmados;
- limites de CPU, RAM, tempo e saída;
- rede desabilitada por padrão por ferramenta;
- ações destrutivas não são autorrecuperáveis: exigem aprovação.

## Portas reservadas

| Porta | Serviço | Binding | Exposição |
|---:|---|---|---|
| 8443 | Casulo Gateway/PWA | LAN selecionada | Dispositivos pareados |
| 8081 | llama-server | 127.0.0.1 | Interna |
| 8082 | ASR | 127.0.0.1 | Interna |
| 8083 | TTS | 127.0.0.1 | Interna |
| 8084 | supervisor/worker | 127.0.0.1 | Interna |

Portas são defaults e podem mudar após auditoria. A regra de exposição não muda.

## Localização dos processos

Prioridade para o sprint:

- Windows: áudio, driver, aceleração, runtime de inferência quando mais rápido;
- WSL2: núcleo, testes, ferramentas, QEMU e workflows Linux;
- Gateway: lado que oferecer integração estável com os serviços e a LAN, sem duplicar modelos.

Escolha final somente após benchmark. Não manter duas cópias residentes do mesmo modelo.

