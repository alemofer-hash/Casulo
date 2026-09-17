# Casulo Cloud — estado standby

```text
release_state = RELEASE_LOCKED
production_bind = DENIED
production_deploy = DENIED
real_credentials = DENIED
production_dns = DENIED
```

O monorepo privado pode compilar e testar protocolo, gateway, autenticação
abstrata, job broker, eventos, policy e observabilidade com adapters in-memory.
O lock é fail-closed: ausência, corrupção ou valor desconhecido nunca libera
produção.

## Implementação comprovada no Sprint 11

- autenticação é um protocolo abstrato; o adapter presente aceita somente
  principals e credenciais fixas de teste;
- policy rejeita contexto excessivo, referências inválidas e qualquer tentativa
  de habilitar treino com conteúdo do usuário;
- o broker possui limite explícito de jobs em voo e backpressure observável;
- `request_id` é idempotente para o mesmo payload e rejeita colisões;
- cancelamento é cooperativo e produz um único evento terminal;
- replay devolve exatamente o stream selado, sem reexecutar o engine de teste;
- falhas registram somente o tipo técnico e não o conteúdo da exceção;
- métricas contêm apenas contadores agregados e declaram
  `contains_user_content=false`;
- variável de ambiente, nome, hostname ou identidade do cliente não consegue
  liberar `production_bind`.

O único transporte executável é `CloudTestHarness`, em memória e test-only.
Não existe bind, DNS, deploy, credencial real nem endpoint de produção.

TLS é obrigatório quando houver processamento remoto. Não será alegado E2EE
quando o servidor precisar processar conteúdo. Contexto remoto será mínimo,
autorizado e efêmero por padrão; treino com conteúdo do usuário é negado por
padrão.

Liberação futura exige nova decisão explícita, target/supply chain de servidor,
threat model, credenciais reais fora do repositório e revisão de privacidade.
