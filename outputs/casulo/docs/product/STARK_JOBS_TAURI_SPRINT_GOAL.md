# GOAL — Stark + Jobs como superfície executável do Casulo

Data de início: 2026-08-20  
Estado inicial: `IN_PROGRESS`  
Trilha: produto owner Hosted; pesquisa científica congelada

## Objetivo

Transformar o protótipo visual sintético produzido no Figma na primeira casca
Tauri 2 executável do Casulo, sem migrar ou reescrever o motor. A casca deve
consumir o contrato de eventos Hosted/Native já selado, mostrar tokens conforme
chegam e representar jobs somente quando há receipt real.

O Sprint termina com código, testes, inspeção visual e um plano causal para
levar o mesmo protocolo de apresentação ao Casulo Native/OS.

## Baseline preservado

- branch: `product/semantic-multiverse`;
- commit: `df12e916c90d9bd2b966326275dc191573f38abd`;
- worktree histórico substancialmente modificado, sem limpeza destrutiva;
- `CREATIVE_INTERLOCUTION_VERTICAL_SLICE_PASS` preservado;
- owner/public/cloud e release RC/T85 não são reconstruídos neste Sprint;
- Cloud `RELEASE_LOCKED`, guest network OFF, USB/block devices proibidos;
- nenhum benchmark científico ou energético.

## Entregas vinculantes

1. app React/Vite/Tauri 2 em `apps/casulo-owner-ui`;
2. dependências locais pinadas e lockfiles versionáveis;
3. bridge Rust somente leitura para o JSONL real `casulo.owner-ux-event/1.0`;
4. allowlist/capabilities mínimas e CSP offline;
5. projeção visual Stark + Jobs original, sem fontes ou assets remotos;
6. tokens incrementais e lifecycle de jobs conduzidos por eventos;
7. fita sintética disponível apenas em modo de design, rotulada e manual;
8. testes de contrato JS, Rust e Python/conformance existentes;
9. build web e build Tauri ou bloqueio ambiental comprovado;
10. inspeção visual em breakpoints de desktop;
11. plano Hosted -> Native/OS sem alegar que WebView é o SO Native.

## Invariantes

- nenhum `setTimeout` ou `setInterval` simula progresso, token ou conclusão;
- nenhum stdout incidental cria estado de produto;
- job sem SHA-256 de evidência é recusado;
- conclusão tardia após cancelamento não é publicada;
- apresentação nunca cria grant, receipt, diagnóstico ou decisão de motor;
- modo sintético nunca é classificado como evidência runtime;
- nenhum `shell=true`, plugin shell, filesystem plugin ou network plugin;
- nenhum componente owner é copiado para public;
- o protótipo Figma permanece referência, não baseline de execução.

## Gates

| Gate | Critério |
| --- | --- |
| SJ0 | baseline, dependências, licenças, disco e toolchains registrados |
| SJ1 | contrato visual e ADR aprovados no código/documentação |
| SJ2 | reducer rejeita eventos inválidos, duplicados e progresso fabricado |
| SJ3 | bridge Rust valida hash, tamanho, path e lifecycle antes de emitir |
| SJ4 | frontend builda offline após lock e não possui conexão externa |
| SJ5 | Tauri compila/testa no Windows com capability mínima |
| SJ6 | visual passa 1280x720 e 1440x900, teclado e reduced motion |
| SJ7 | plano Native mapeia protocolo, reducer, renderer e HAL sem reescrita cega |

## Estado terminal permitido

- `STARK_JOBS_TAURI_VERTICAL_SLICE_PASS`;
- `IN_PROGRESS_CHECKPOINTED`;
- `BLOCKED_EXPLICIT_CONSENT`;
- `BLOCKED_ENVIRONMENT`.

Beleza, química e prazer permanecem `PENDING_GUILHERME`; testes automáticos não
podem aprová-los em seu nome.
