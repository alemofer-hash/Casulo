# RUNBOOK — INSPEÇÃO LIVRE DA PRIMEIRA VM GENERATIVA

Este documento é adaptado pelo Codex aos comandos reais do repositório antes do handoff.

## 1. Objetivo da sessão

Não “aprovar o Casulo”. Descobrir:

- como é conversar com o primeiro motor;
- onde a química aparece ou morre;
- quando ele parece brilhante ou superficial;
- se consegue gerar o agente desejado;
- onde a latência incomoda;
- quais interrupções funcionam;
- o que a forma visual comunica;
- o que Guilherme quer mudar depois.

## 2. Preparação segura

O launcher deve mostrar:

```text
VM profile
base image hash
overlay path
model/runtime
espaço livre atual
snapshot atual
rede owner: denied/offline
Cloud: RELEASE_LOCKED
external media: NOT_IN_USE
```

Antes da primeira sessão:

1. rodar `casulo vm doctor`;
2. confirmar que o target é arquivo regular;
3. criar snapshot `before-guilherme-inspection`;
4. confirmar reserva de disco;
5. iniciar VM;
6. permitir microfone/playback somente após consentimento;
7. manter fallback textual disponível.

## 3. Primeira conversa

Guilherme não deve usar um roteiro preparado pelo engine. Sugestão de início apenas para orientação:

> “Cara, quero inventar um agente agora. Ainda não sei exatamente a forma. Me ajuda a desenvolver a ideia comigo.”

Depois, escolher uma necessidade ou ideia real daquele momento. O valor da sessão está em o pedido não ter sido preparado para os testes.

Observar:

- ele captou o núcleo ou apenas parafraseou?
- trouxe consequência inteligente?
- discordou quando havia motivo?
- perguntou demais ou de menos?
- manteve calor sem bajular?
- começou a construir antes de a conversa estar madura?
- conseguiu mostrar o agente surgindo?
- respeitou correções localizadas?

## 4. Comandos de inspeção

O produto deve aceitar equivalentes naturais:

```text
“Marca isso: a resposta ficou corporativa.”
“Anota que eu gostei desse tipo de discordância.”
“Quero mudar a voz depois; está lenta demais.”
“Salva um ponto antes de eu testar outra direção.”
“Volta ao snapshot anterior.”
“Mostra o que mudou no agente.”
“Quero ver os detalhes técnicos agora.”
“Esconde os detalhes técnicos.”
```

Notas nunca alteram automaticamente o CollaborationContract ou o produto. Elas registram desejo para a próxima etapa.

## 5. Liberdade para mexer

Guilherme pode:

- iniciar várias conversas;
- abandonar e retomar criações;
- interromper o Guide;
- testar modos expansão/cristalização;
- pedir uma abordagem diferente;
- criar snapshots;
- materializar agentes descartáveis;
- reiniciar a VM;
- provocar falhas seguras;
- usar modo técnico opt-in;
- restaurar o estado limpo.

Ele não precisa proteger a imagem base: toda experimentação ocorre no overlay. Restore/reset deve ser possível sem apagar feedback exportado.

## 6. Eixos de avaliação humana

### Inteligência percebida

- profundidade;
- velocidade de compreensão;
- qualidade das hipóteses;
- capacidade de conectar ideias;
- utilidade da discordância;
- competência para construir.

### Química

- calor;
- naturalidade;
- ritmo;
- humor;
- conforto com silêncio;
- sensação de trabalho conjunto;
- ausência de bajulação e pressão.

### Criação

- fidelidade à ideia;
- qualidade do primeiro agente;
- facilidade de corrigir;
- clareza da forma visual;
- transparência das limitações;
- materialização útil.

### Experiência

- voz;
- latência;
- interrupção;
- visual;
- excesso ou falta de informação;
- estados confusos;
- desejos de design.

## 7. Encerramento

Ao terminar:

1. pedir ao Casulo um resumo das notas, sem reinterpretá-las como decisões;
2. exportar feedback;
3. salvar snapshot se houver criação valiosa;
4. desligar graciosamente;
5. verificar integridade do overlay;
6. preservar o pacote para o próximo GOAL.

Saída esperada:

```text
owner-inspection-feedback/
  session.json
  notes.jsonl
  creation_refs.json
  state_markers.json
  desired_changes.md
  environment_manifest.json
  SHA256SUMS
```

Somente depois desta inspeção será escrito o GOAL de design final e dispositivo externo.

