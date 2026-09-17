# Terceira falha de inspeção humana — Einstein

Estado: `IN_PROGRESS_CHECKPOINTED`

## Causa

A CreationSpec confirmada era válida no schema `casulo.creation/1.0` e não
possuía `content.identity.name`. Esse campo é opcional; a identidade obrigatória
é `creation_id`. O renderer atravessava o dicionário cru e assumia a variante
`identity.name.value`, criando um contrato mais estreito que o domínio.

O `run_probe` havia concluído geração T, quatro reparos por diagnostics,
compilação, simulação, materialização, execução externa, importação round-trip e
publicação da sessão Semantic Multiverse. A falha aconteceu apenas depois disso,
ao iniciar a timeline visual. O archive preservado tem SHA-256
`93650a516d1340c84c15efe9aba5b18064b6f4d7115256f1b6f8bace31c7d9d1`.

## Limite científico da criação original

A criação original não implementava as equações de campo de Einstein. O T e o
`agent.py` materializados eram um agente genérico de leitura de memória; termos
como conexão, Ricci, escalar de Ricci, tensor de Einstein e resíduo não estavam
no código. O antigo holdout comprovava presença de texto, não matemática.

## Correção

- documentos serializados viram `CreationSpec` tipada na borda;
- `CreationPresentation` é uma projeção total para todas as identidades válidas;
- nome ausente usa `creation_id`, com diagnóstico, sem inventar nome;
- schema futuro e documento parcial falham antes de criar o diretório visual;
- erro visual produz receipt recuperável e preserva `:export`, `:nota`,
  `:universos` e `:sair`;
- restore sem snapshot é recusado antes da mutação, sem traceback;
- holdout usa `rg` quando disponível e scanner Python literal limitado como
  fallback;
- o archive original passou por importação, round-trip, reedição localizada e
  renderização de 12 estados sem ser mutado.

## Nova criação científica delimitada

A repetição inédita usa o Qwen3-4B local. O plano científico precisou de quatro
tentativas e recebeu diagnostics reais por entradas, outputs, escopo local 4D e
recusa de alegação global. A implementação materializada:

- exige métrica 4x4, coordenadas e ponto, G/c/Lambda, tensor energia-momento,
  condições iniciais e de contorno, passo de derivada e tolerâncias;
- constrói conexão de Levi-Civita, Ricci, escalar de Ricci, tensor de Einstein e
  resíduo das equações;
- usa diferenças finitas centrais e expressões AST allowlisted;
- recusa dimensão diferente de quatro, métrica assimétrica/singular, símbolos
  ou operações inseguros e tolerâncias fora do envelope;
- declara explicitamente que não integra o problema global não linear, nem
  prova validade física, estabilidade, convergência ou unicidade.

Minkowski no vácuo foi usado como validação mínima e retornou resíduo máximo
zero. Isso valida o avaliador local desse caso, não um solucionador geral.

## Evidência

- preservação: `product-demos/semantic-multiverse/inspection-failure-3-einstein-preserved/`;
- nova criação: `product-demos/semantic-multiverse/inspection-failure-3-einstein-rerun/`;
- evidência integrada SHA-256: `003f5644e8f12a57478f795b799405fede46b23c6b18c4ca6e99000a60d678d5`;
- pacote científico SHA-256: `554da5a1341f84077c0434f79b9dacd00ba6d5dd96869a91deb92b93002c7860`;
- TCAP SHA-256: `fadf8a19c7d0923fb8c35b57994695a0982ebebf1bd528efb50ec0ea5545475d`;
- rota: `intencao -> sinais -> engenharia -> diagnostico -> interface -> materializacao`;
- lifecycle receipts: 28; transition receipts: 5; HOT final:
  `materializacao`; HOT após reboot: vazio;
- snapshot/restore: três boots aprovados, base imutável;
- regressão: 259 passed, 1 skipped;
- Native: `cargo +nightly-2026-02-01 -Z bindeps check --locked` PASS;
- public: 12 arquivos, zero componente privado.

Cloud permanece `RELEASE_LOCKED`; public congelado; USB, block devices e QPU
continuam proibidos. Nenhum benchmark científico foi iniciado.
