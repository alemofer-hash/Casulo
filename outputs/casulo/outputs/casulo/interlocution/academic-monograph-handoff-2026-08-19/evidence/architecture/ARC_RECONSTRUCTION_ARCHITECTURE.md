# Casulo — reconstrução orientada à intenção

Data: 2026-08-18  
Estado: arquitetura vinculante em implementação incremental  
Nome interno do programa: `ARC`

## Tese operacional

O Casulo não tenta substituir álgebra neural por sintaxe. Ele reduz primeiro o
trabalho neural que nunca deveria ter existido: geração prematura, contexto sem
relevância, tentativas descartadas, reparo global e execução antes de entender o
pedido.

A unidade central deixa de ser o prompt e passa a ser o `IntentTwin`: uma
representação versionada da finalidade observada, das interpretações possíveis,
das incertezas materiais, da hipótese escolhida e dos requisitos confirmados.

O objetivo técnico é maximizar:

```text
intenção confirmada e verificada cumprida
-----------------------------------------------------------
compute neural + working set + retrabalho + fricção humana
```

Isso não prova que T substitui pesos, kernels, vetorização ou multiplicações de
matrizes. T assume autoridade sobre seleção, políticas, transições, requisitos,
evidência, compilação e ciclo de vida. O runtime neural continua uma primitive
estrangeira subordinada e substituível.

## Fluxo reconstruído

```text
expressão humana incompleta
  -> observações EXPLICIT / INFERRED
  -> duas hipóteses concorrentes
  -> maior lacuna material, se existir
  -> uma pergunta de alto ganho de informação
  -> IntentTwin visível
  -> confirmação humana explícita
  -> RequirementGraph com proveniência
  -> fatos de autoridade consumíveis por T
  -> CreationSpec
  -> geração e compilação T
  -> diagnostics e reparo limitado
  -> simulação sem efeitos reais
  -> evidências independentes por requisito
  -> materialização
  -> memória de decisões, inclusive rejeitadas
```

Conversa comum não é forçada por esse funil. Exploração pode permanecer aberta;
produção material não.

## Invariantes

1. O modelo propõe observações, hipóteses e rotas; nunca cria confirmação ou
   capability grant.
2. Lacuna material aberta bloqueia produção.
3. Hipótese inferida só ganha autoridade depois de aparecer no espelho e receber
   confirmação humana explícita.
4. `RequirementGraph` só nasce de `IntentTwin` confirmado e preserva eventos de
   origem.
5. Compilar fatos para T não significa aprovar o resultado. Evidência
   independente ainda é obrigatória.
6. O renderer recebe tipo validado, nunca o dicionário cru produzido pelo
   modelo.
7. O caminho de produto não exige falha artificial do primeiro candidato.
8. O modelo já residente é reutilizado durante criação; uma segunda carga não é
   trabalho útil.
9. Correção futura deve recompilar o menor subgrafo afetado.
10. Cloud continua `RELEASE_LOCKED`; owner continua local e sem API externa.

## Roadmap reconstruído

| Marco | Entrega | Critério de saída | Estado em 2026-08-18 |
|---|---|---|---|
| ARC-0 | Congelar evidência T85 e retirar benchmark do caminho de produto | nenhum selo histórico alterado; benchmark não iniciado | PASS prévio |
| ARC-1 | Domínio `IntentTwin` | tipos, hashes, proveniência, lacunas e confirmação fail-closed | IMPLEMENTADO_TESTADO |
| ARC-2 | Reconstrutor neural local | uma hipótese quando claro; duas quando há bifurcação; até uma lacuna e refino estruturado | RUNTIME_REAL_E_COMPATIBILIDADE_SINTETICA_PASS |
| ARC-3 | Espelho vivo na interface | usuário vê leituras, impactos, lacuna e resumo antes de `CONFIRMO` | READY_FOR_GUILHERME_PROOF |
| ARC-4 | Autoridade semântica T | IntentTwin confirmado vira RequirementGraph e fatos T; HARD só conclui com receipt independente | IMPLEMENTADO_TESTADO; E2E_NEURAL_PENDENTE |
| ARC-5 | Worker de produto | runtime quente reutilizado, zero holdout scan e zero falha artificial obrigatória | IMPLEMENTADO; E2E_NEURAL_PENDENTE |
| ARC-6 | Reparo causal | diagnostics ligam requisito -> unidade T -> subgrafo; rebuild mínimo comprovado | IMPLEMENTADO_TESTADO; OWNER_NEURAL_HUMAN_PROOF_PENDENTE |
| ARC-7 | Orçamento neural | roteador escolhe conversa, reconstrução curta ou síntese; contexto suficiente mínimo | IMPLEMENTADO_TESTADO; QUALIDADE_OWNER_PENDENTE |
| ARC-8 | Fronteira matemática | medir kernels restantes; especializar/fundir com T somente onde preservar semântica e vencer baseline local | IMPLEMENTADO_TESTADO_NO_KERNEL_LIVING_MEMORY; SEM_CLAIM_GERAL |
| ARC-9 | Casulo agradável | presença instantânea, streaming real, jobs em background e forma viva sem painel técnico | IMPLEMENTADO_TESTADO; HUMAN_UX_PROOF_PENDENTE |
| ARC-10 | Convergência Native | Hosted e Native compartilham contratos; drivers migram sem bloquear UX | CONTROL_PLANE_IMPLEMENTADO_E_BOOT_QEMU_PASS; DRIVERS_PESADOS_HOSTED |
| ARC-11 | Prova humana final | Guilherme boota, conversa, cria algo inédito, corrige, materializa, reinicia e retoma sem P0/P1 | PENDENTE_GUILHERME |

## O que foi implementado neste slice

- `casulo.product.intent_reconstruction` contém o contrato imutável, hash
  canônico, bloqueio de lacunas, confirmação humana e projeção para
  `RequirementGraph`.
- `casulo_owner.intent_reconstruction` usa o Qwen local por JSON Schema para
  formar duas hipóteses e, quando necessário, uma pergunta material.
- As hipóteses disputam a mesma dimensão, declaram valores mutuamente
  excludentes e passam por até dois candidatos; rejeições estruturais reais
  alimentam um repair neural curto e ficam registradas.
- `:criar` agora reconstrói, mostra, pergunta, confirma e só depois inicia a
  ponte de criação.
- O worker recebe o `IntentTwin`, persiste o grafo e compila os fatos esperados
  para a autoridade T antes da síntese.
- O `LocalModelRuntime` já aberto é reaproveitado. A carga duplicada foi removida
  dessa rota.
- Holdout scan e “primeira tentativa precisa falhar” continuam disponíveis para
  a prova histórica, mas são desativados explicitamente no modo de produto.

## Limite atual mais importante

O transporte do `RequirementGraph` para T e o gate de evidência estão
implementados sem falsa aprovação. O arquivo nasce como
`AWAITING_INDEPENDENT_EVIDENCE`; depois de compile, teste de aceite, simulação e
execução limpa, o gate emite receipts. Qualquer HARD em `UNKNOWN` ou `FAIL`
bloqueia a materialização. Verificadores de domínio ainda sem adapter permanecem
deliberadamente `UNKNOWN`.

## ARC-6 implementado

`RequirementSemanticBinding`, `CausalRepairPlan` e `CausalRepairReceipt` agora
ligam requisitos confirmados aos `watch_paths` das unidades T. Diagnóstico sem
requisito causal é recusado no modo owner; requisito HARD sem unidade conectada
reprova o candidato ainda na síntese. O T Forge reconstrói as sementes
semânticas e dependentes transitivos, preservando hashes fora do subgrafo.

A evidência determinística válida está em
`product-demos/human-proof/arc-causal-repair-2026-08-18-attempt2`. Ela não é
apresentada como prova neural owner.

## Próximo passo exato

ARC-9 entrega protocolo tipado, streaming emitido pelo runtime, trabalho de
criação em background, cancelamento e uma superfície conversacional mínima. A
prova mecânica está em
`product-demos/human-proof/arc-pleasant-interface-2026-08-18-attempt2`; química,
voz e prazer de uso permanecem pendentes de Guilherme.

ARC-10 levou o contrato selado de presença, streaming e jobs ao perfil Native e
o executou em boot QEMU real. Inferência, voz, memória protegida, renderer e
materialização continuam Hosted de forma explícita.

O próximo marco é ARC-11, prova humana final. Guilherme deve executar o launcher
ARC-9 e registrar fricções P0/P1; automação não pode aprovar a experiência em
nome dele.
