# ARC-7 — orçamento neural e contexto suficiente

Data: 2026-08-18  
Estado técnico: `IMPLEMENTED_AND_TESTED`  
Qualidade neural owner inédita: `PENDING_GUILHERME`

## Resultado

O caminho owner deixou de usar uma política neural global implícita. Cada uso
do Qwen agora começa por uma operação declarada pelo produto, recebe um budget
fixo e produz uma decisão com proveniência e SHA-256:

```text
evento real
  -> NeuralRouteRequest
  -> NeuralBudgetRouter determinístico
  -> gates da operação
  -> NeuralRouteDecision
  -> seleção de contexto suficiente
  -> SamplingPolicy limitada
  -> inferência local
  -> receipt
```

O modelo não escolhe seu próprio budget, não converte resposta em confirmação e
não pode ampliar o teto por meio de uma `SamplingPolicy` customizada.

## Budgets congelados

Todos os budgets assumem a janela física corrente de 8.192 tokens do
`llama.cpp`. O teto em bytes UTF-8 é conservador: com byte fallback, a entrada
não exige mais tokens que bytes. Uma reserva adicional de 256 tokens cobre o
chat template e tokens de controle.

| Operação | Família | Entrada máxima UTF-8 | Saída máxima | Gate material |
|---|---|---:|---:|---|
| `DIALOGUE` | dialogue | 5.632 B | 768 tokens | proveniência |
| `INTENT_RECONSTRUCTION` | planning | 6.400 B | 768 tokens | proveniência |
| `INTENT_REFINEMENT` | planning | 6.144 B | 768 tokens | lacuna material aberta |
| `SEMANTIC_ROUTING` | planning | 7.424 B | 384 tokens | proposta sem authority |
| `T_SYNTHESIS` | code | 6.400 B | 1.536 tokens | confirmação humana + requisito HARD |
| `T_REPAIR` | code | 7.424 B | 384 tokens | confirmação + diagnostic real |

Para toda linha vale:

```text
max_prompt_utf8_bytes
+ max_generated_tokens
+ prompt_token_safety_margin
<= runtime_context_tokens
```

O orçamento é capacidade máxima, não meta de consumo.

## Contexto suficiente

No diálogo, restrições duras e a fala corrente são obrigatórias. Se elas não
couberem, o turno falha; nunca são cortadas. O restante é selecionado por
prioridade estável:

- até oito mensagens recentes;
- até doze memórias melhor priorizadas;
- conteúdo importado permanece marcado `IMPORTED_UNTRUSTED`;
- cada inclusão e descarte aparece no `NeuralBudgetReceipt`;
- o receipt registra caracteres, bytes UTF-8, hash do contexto e proveniência.

O limite é conferido novamente imediatamente antes das chamadas estruturadas de
reconstrução, refino, roteamento, síntese e reparo. Exceder o budget produz erro
explícito em vez de depender de truncamento interno do runtime.

## Integração owner

- diálogo: `ContextAssembler`, `OwnerGenerativeEngineAdapter` e
  `casulo_owner_vm_inspect.py` persistem receipts append-only;
- intenção: `IntentReconstruction` preserva decisões de reconstrução e refino;
- Semantic Multiverse: cada proposta neural inclui sua decisão de rota;
- T Forge: projeto sintetizado preserva a decisão `T_SYNTHESIS`; revisão causal
  acrescenta `T_REPAIR` somente depois de diagnostic real;
- worker: checkpoint e manifest da criação transportam todas as decisões.

Rotas históricas sem `IntentTwin` continuam reproduzíveis, mas não recebem a
alegação ARC-7 do caminho owner atual.

## Evidência

Smoke append-only vigente:

`product-demos/human-proof/arc-neural-budget-2026-08-18-attempt2`

- classificação:
  `DETERMINISTIC_BUDGET_CONTRACT_SMOKE_NOT_OWNER_NEURAL_QUALITY_PROOF`;
- gate: PASS;
- receipt de contexto:
  `f3849f9d2921a724b188788b57f6809b55c4b18d0aeeb594231b3e29b3237512`;
- SHA-256 do `MANIFEST.json`:
  `d4950f34f123f45ebdf925d2a816d807c52917a5a9e6971c5dbae87e43e9d9cc`;
- regressão focal final: `57 passed`;
- regressão integral: `494 passed, 1 skipped`;
- `compileall`: PASS.

O `attempt1` fica preservado como primeira iteração, mas foi superseded porque
limitava caracteres sem ainda provar o teto conservador em bytes UTF-8.

## Limites

ARC-7 prova seleção, gates, accounting e integração. Não prova que 5.632 bytes
são o ótimo de qualidade, que o Qwen compreendeu uma criação inédita ou que o
sistema venceu outro modelo. Ajustes futuros exigem receipts comparáveis e não
podem ser feitos depois de observar uma resposta para favorecê-la.

Nenhum benchmark científico, API externa, Cloud, USB ou prova humana foi
iniciado.

## Próximo passo

ARC-8 deve inventariar a fronteira matemática real: identificar kernels ainda
estrangeiros e, em cada candidato, exigir equivalência semântica antes de
especialização/fusão em T. O trabalho será microprofiling de produto, não a
reativação das campanhas científicas históricas nem claim de superioridade.
