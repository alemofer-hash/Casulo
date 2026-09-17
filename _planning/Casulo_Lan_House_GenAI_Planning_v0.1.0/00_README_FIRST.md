# CASULO LAN HOUSE GENAI — PLANNING & ORCHESTRATION v0.1.0

Data de congelamento: 2026-09-17  
Host canônico: `C:\Users\guimo\Downloads\ex`  
Servidor principal: notebook Intel Core i5, 16 GB RAM, GPU integrada, SSD 256 GB, 127 GB livres.

## Missão

Construir em dez dias consecutivos o **CASULO FAMILY RP0.1**, uma infraestrutura de IA familiar local na qual o notebook é o centro de operações. O motor generativo roda apenas no laptop; celulares e computadores autorizados acessam o serviço por uma PWA via HTTPS na rede local.

O sistema deve funcionar sem assinatura, sem chave de API e sem serviço de inferência externo. A internet pode ser usada na preparação, em atualizações deliberadas ou como fonte consultada por ferramenta separada, mas nunca será necessária para a inferência principal.

## Comece aqui

1. Leia `01_PROMPT_GOAL_CODEX.md` e entregue seu conteúdo ao Codex no diretório canônico.
2. Execute `scripts/00-preflight-readonly.ps1` no PowerShell. Ele não instala nem altera o sistema.
3. Conclua `06_STAGE_ZERO_GIT_BACKUP.md` antes de reorganizar qualquer arquivo existente.
4. Só depois use `scripts/02-install-windows-core.ps1 -Apply` e o instalador WSL.
5. Siga os gates em `07_TEN_DAY_EXECUTION_PLAN.md`; falha de gate interrompe promoção, não autoriza apagar trabalho.

## Estado pretendido

```text
Telefone/PWA --HTTPS--> Casulo Gateway --loopback--> modelo local
                                  |---> voz local
                                  |---> memória por usuário
                                  |---> fila/scheduler
                                  |---> ferramentas com aprovação
```

## Regras invioláveis

- `llama-server`, Whisper e TTS não são expostos diretamente à LAN.
- Sem encaminhamento de porta no roteador, UPnP ou exposição pública.
- Um trabalho generativo pesado por vez; os demais entram em fila.
- Nenhum áudio bruto é persistido por padrão.
- Nenhum dado de um familiar aparece no contexto de outro.
- Escrita, shell, exclusão e ações administrativas exigem política e aprovação.
- O modelo propõe; o Casulo valida, executa, testa, registra e pode reverter.
- Nenhum arquivo existente em `ex` é apagado ou reformatado antes do snapshot Stage Zero.

## Conteúdo do pacote

- prompt mestre `/GOAL`;
- constituição do produto e arquitetura;
- orçamento de RAM, SSD e desempenho;
- lista obrigatória de instalações;
- procedimento de backup Git Stage Zero;
- roteiro de dez dias;
- segurança, pareamento e política de rede;
- estratégia de modelos locais;
- matriz de testes e aceitação;
- runbook de operação;
- scripts PowerShell/Bash com fail-closed;
- manifestos e templates para o repositório.

## O que não está dentro deste ZIP

Pesos GGUF, instaladores, caches de pacotes, certificados privados, dados familiares e o repositório Casulo. Eles são grandes, sensíveis ou mutáveis. O pacote contém os manifestos, caminhos, verificações e procedimentos necessários para adquiri-los e congelá-los localmente.

