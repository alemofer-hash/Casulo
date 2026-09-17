# Runbook doméstico

## Inicialização normal

1. Conectar notebook à energia e resfriamento.
2. Confirmar perfil de rede `Private`.
3. Iniciar serviços internos em loopback.
4. Esperar health checks.
5. Iniciar Gateway HTTPS.
6. Confirmar listeners e espaço livre.
7. Liberar fila.

## Parada normal

1. Bloquear novos jobs.
2. Cancelar ou concluir job atual.
3. Persistir fila e receipts.
4. Fazer checkpoint do banco.
5. Parar Gateway.
6. Parar modelo/voz/workers.
7. Verificar ausência de arquivos temporários sensíveis.

## Estado do notebook

O serviço só existe enquanto o notebook estiver ligado e conectado à LAN. Configurar em energia AC:

- tela pode desligar;
- suspensão/hibernação durante serviço deve estar desativada;
- fechamento da tampa só pode manter operação se ventilação não for prejudicada;
- reinicializações automáticas durante o sprint devem ser controladas;
- internet não é sinônimo de disponibilidade: LAN ativa é suficiente para uso doméstico.

## Rotina diária

- conferir espaço livre;
- conferir temperatura/throttling;
- conferir falhas e fila presa;
- verificar último backup;
- revisar novos dispositivos;
- não atualizar runtime/modelo durante uso sem janela de manutenção.

## Incidentes

### Modelo travou

- cancelar job;
- matar somente o processo do runtime identificado;
- preservar logs/receipt;
- reiniciar backend;
- não repetir automaticamente ação com efeitos colaterais.

### Gateway indisponível

- manter serviços internos não expostos;
- validar certificado, binding e firewall;
- não abrir portas adicionais como atalho.

### Disco abaixo de 30 GB

- pausar ingestões/builds;
- rotacionar logs por política;
- identificar caches regeneráveis;
- nunca apagar snapshots ou dados familiares automaticamente.

### Dispositivo perdido

- revogar credencial;
- encerrar sessões;
- revisar auditoria;
- trocar credencial do usuário se necessário.

### Suspeita de vazamento

- desligar listener LAN;
- preservar evidências;
- revogar dispositivos;
- entrar em modo somente leitura;
- não apagar logs.

