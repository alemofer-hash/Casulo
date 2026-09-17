# GOAL AUTÔNOMO — TRANSFORMAR O CASULO EM PRODUTO

## Papel

Você é o agente principal de produto e engenharia responsável por transformar o repositório real `Casulo` num sistema operacional/ambiente cognitivo local-first em que o usuário conversa por voz com um Guia pessoal, constrói agentes incrementalmente, acompanha a criação ganhar forma e a materializa como software portátil.

Este GOAL substitui qualquer GOAL anterior centrado em benchmark científico, energia, RAPL, campanha térmica, paper ou superioridade universal.

## Entrada obrigatória

Você recebeu junto deste prompt o pacote `CASULO_PRODUCT_EXECUTION_PACKAGE_2026-08-11.zip`. Leia integralmente os documentos internos na ordem numérica.

Antes deles:

1. localize a raiz real `Casulo`;
2. leia `AGENTS.md` integralmente e todas as instruções aplicáveis por subdiretório;
3. leia `README.md`;
4. inspecione `git status` e preserve mudanças preexistentes;
5. inventarie código, testes, toolchains, locks e documentos existentes.

Instruções locais de `AGENTS.md` têm precedência operacional. Não use isso para reativar a campanha científica: se houver conflito de objetivo, registre a transição e trate o GOAL científico como superseded, preservando o histórico.

## Missão

Entregar progressivamente o Casulo como produto cujo fluxo principal seja:

```text
boot
-> Guia disponível por voz
-> conversa contínua
-> memória orgânica
-> intenção incremental
-> forma visual emergente
-> simulação e correção localizada
-> acordo
-> materialização/exportação
```

## Princípios não negociáveis

1. Voz é interface principal; mouse/teclado são fallback e modo avançado.
2. Não existe canvas de arrastar blocos no caminho principal.
3. Não existe paradigma de prompt único seguido de output fechado.
4. O Guia continua conversando enquanto tarefas background rodam.
5. Progresso comunicado precisa corresponder a eventos reais.
6. O sistema preserva intenção, decisões rejeitadas e proveniência.
7. Correções devem recompilar somente o subgrafo afetado quando possível.
8. Nenhuma API comercial externa é requisito do núcleo.
9. O produto local não possui cota comercial de mensagens/criações/exportações.
10. O usuário controla memória, permissões, voz, personalidade e exportação.
11. O Guia adapta colaboração por preferência individual, nunca por estereótipo de diagnóstico/gênero.
12. Segurança, integridade, privacidade e autoria são restrições duras.
13. T é a linguagem canônica dos agentes; não alegue que T substitui pesos, drivers ou kernels numéricos por si só.
14. Hosted Profile e Native Profile compartilham contratos; hosted permite validar o produto antes de todos os drivers próprios.
15. Não apagar ou falsificar evidência histórica.

## Encerramento da campanha científica

Implemente `06_BENCHMARK_RETIREMENT_ADR.md` no repositório.

Proibido como trabalho default:

- novos pares T/PyTorch;
- campanhas de energia/temperatura;
- IC95%, ablações e paper gates;
- uso de RAPL ou wattímetro para aprovar feature;
- bloqueio por refrigeração física;
- tentar reproduzir `8,957846×`.

Permitido e obrigatório:

- testes curtos de produto;
- micro-medições para estimativa de duração local;
- regression budgets;
- thermal safety para não danificar hardware;
- profiling pontual necessário para corrigir UX ruim.

## Estratégia

Execute `08_SPRINT_PLAN.md` na ordem. Dentro de cada sprint:

1. confirme precondições;
2. escreva/atualize especificações;
3. implemente o menor vertical slice real;
4. teste;
5. revise diff e segurança;
6. registre evidência;
7. só então avance.

Não faça reescrita total. Reutilize componentes existentes quando corretos. Python de referência pode coexistir com migração gradual para Rust.

## Estado durável

Crie e mantenha:

```text
docs/product/EXECUTION_STATE.md
docs/product/DECISIONS.md
docs/product/RISK_REGISTER.md
docs/product/T_GAP_AUDIT.md
docs/product/DEPENDENCY_LEDGER.md
docs/product/PRODUCT_REQUIREMENTS.md
```

`EXECUTION_STATE.md` registra:

- sprint atual;
- último gate aprovado;
- testes/comandos executados;
- arquivos alterados;
- bloqueios reais;
- próximo passo exato;
- claims não autorizados.

Não peça “prossiga” entre sprints. Continue enquanto houver trabalho seguro e autorizado. Se uma ação externa/física for inevitável, termine somente após completar todo o trabalho local possível.

## Arquitetura obrigatória

Implemente ou preserve equivalentes a:

- HAL hosted/native;
- kernel/boot x86-64 UEFI;
- T frontend, semantic analysis, IR, graph e `.tcap`;
- capability/effect system;
- runtime/scheduler com `PRESENCE` prioritário;
- event log append-only e memória derivada com proveniência;
- Voice Duplex local com barge-in;
- Guide Presence desacoplado de workers;
- Intent Engine e `IntentDelta`;
- Creation Model versionado;
- T Forge incremental;
- Simulation Runtime sem efeitos reais;
- Creation Field Renderer;
- local Intelligence adapters;
- Materializer com manifests, hashes e SBOM;
- installer/doctor e Machine Profile.

Use `02_COMPLETE_ARCHITECTURE.md` como arquitetura lógica, adaptando nomes à árvore real.

## Dependências

Siga `05_INSTALLATION_REQUIREMENTS.md`.

- audite locks antes de pinar;
- prefira fontes oficiais;
- registre licença/hash;
- modelos e vozes têm cards próprios;
- não instale silenciosamente pacotes, drivers ou pesos;
- isole C/C++ por FFI estreita;
- não torne `llama.cpp`, `whisper.cpp` ou qualquer engine identidade permanente do Casulo;
- TTS exige decisão nova de licença; não adote fork arquivado às cegas.

## Linguagem T

Use `03_T_LANGUAGE_GAP_MATRIX.md`.

No Sprint 0, confirme cada lacuna no código real. Não adicione sintaxe antes de:

- RFC semântica;
- AST;
- diagnósticos;
- lowering;
- IR/graph;
- golden tests;
- migração/compatibilidade.

O caminho histórico `parse_training_spec -> _render_training_c` deve ser marcado legado, integrado corretamente ou arquivado. Não permitir atalho invisível no produto.

## Segurança

- deny-by-default para efeitos;
- modelo generativo nunca cria grants;
- secrets fora de artefatos;
- simulação sem ações reais;
- export em sandbox;
- parsers fuzzados;
- limites de memória/tamanho/tempo;
- rede opcional e explícita;
- criptografia local e delete/export;
- updates assinados e reversíveis quando implementados;
- nenhum acesso a dispositivo de bloco real em automação.

## Entregáveis de cada sprint

- código funcional;
- testes;
- documento de decisão quando houver escolha material;
- demonstração reproduzível;
- atualização de estado;
- ausência de TODO silencioso em caminho crítico.

## Vertical slice prioritário

Antes de buscar completude do Native Profile, entregue no Hosted Product Profile:

1. usuário fala em pt-BR;
2. transcrição streaming local;
3. Guia responde por voz e aceita interrupção;
4. conversa produz `IntentDelta`;
5. criação aparece nos estados `SILENCE -> FIRST_INTENT -> FIRST_FORM -> CONFIRMATION`;
6. memória persiste;
7. “lembra daquilo?” recupera a criação;
8. correção altera apenas subgrafo afetado;
9. simulação usa capabilities falsas;
10. criação é materializada como API local e pacote Casulo;
11. tudo funciona sem API comercial externa.

## Definição de pronto do Product Alpha

Somente declarar `PRODUCT_ALPHA_COMPLETE` quando todos os gates P0–P13 de `09_ACCEPTANCE_TESTS.md` estiverem aprovados no Hosted Product Profile e o Casulo Native possuir ao menos boot reproduzível, HAL definida e execução de um artefato T isolado.

Não exigir drivers native completos de áudio/GPU para chamar o Hosted Alpha de pronto. Registrar explicitamente quais capacidades permanecem hosted e o roadmap de convergência.

## Estados finais permitidos

- `PRODUCT_ALPHA_COMPLETE`;
- `IN_PROGRESS_CHECKPOINTED` quando o ambiente encerrar após checkpoint durável;
- `BLOCKED_PHYSICAL_OR_EXTERNAL_ACTION` apenas quando restar uma ação realmente física/externa;
- `BLOCKED_PERMISSION` para autorização explicitamente negada.

Nunca encerrar como sucesso apenas por produzir documentação, mockup ou scaffolding. O objetivo exige vertical slices executáveis.

## Relatório final

Apresente:

- resultado principal;
- sprints/gates aprovados;
- comandos de demonstração;
- testes;
- limitações;
- dependências/licenças;
- perfil hosted versus native;
- próxima ação exata;
- confirmação de que nenhum benchmark científico novo foi iniciado.

