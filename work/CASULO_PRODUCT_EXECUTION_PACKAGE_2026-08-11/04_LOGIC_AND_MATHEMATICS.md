# LÓGICA E MATEMÁTICA OPERACIONAL

Este documento define modelos implementáveis. Fórmulas são contratos de engenharia, não alegações científicas de superioridade.

## 1. Estado vivo da criação

Seja:

- `C_t`: estado canônico da criação na versão `t`;
- `D_t`: delta de intenção;
- `K`: conjunto de invariantes duras;
- `P`: política de capabilities.

```text
C_(t+1) = Apply(C_t, D_t)
```

somente se:

```text
Validate(C_(t+1), K, P) = PASS
```

Caso contrário, o delta permanece `PROPOSED`, nunca altera o estado confirmado.

## 2. Detecção de impacto

Modele a criação como grafo dirigido `G=(V,E)`. Um delta altera conjunto `A ⊆ V`.

O conjunto mínimo a recompilar é:

```text
Impact(A) = A ∪ Descendants_data(A) ∪ Descendants_control(A)
```

Capacidades, schemas ou políticas podem exigir fechamento adicional. Todo nó fora de `Impact(A)` deve preservar hash; mudança injustificada falha o teste de correção localizada.

Métrica:

```text
R_rework = |Impact(A)| / |V|
```

## 3. Consolidação de intenção

Uma intenção inferida tem estado:

```text
PROVISIONAL -> PROPOSED -> CONFIRMED -> SUPERSEDED
                         -> REJECTED
```

Confiança do modelo nunca substitui confirmação quando o delta:

- aumenta capabilities;
- altera retenção de memória;
- cria ação externa;
- implica custo não limitado;
- remove restrição anterior;
- é irreversível.

## 4. Recuperação de memória

Para consulta `q`, cada memória `m` recebe score interno:

```text
S(m,q) =
  w_s * semantic_similarity(m,q)
  + w_r * recency(m)
  + w_c * creation_affinity(m)
  + w_o * open_thread(m)
  + w_p * provenance_strength(m)
  + w_u * user_reference_pattern(m,q)
  - w_x * contradiction_penalty(m)
```

Regras duras:

- decisão rejeitada não pode reaparecer como atual;
- memória derivada aponta para evento bruto;
- baixa margem entre dois candidatos materiais gera esclarecimento;
- raw history não é apagado por sumarização;
- exclusão solicitada remove índices, projeções e blobs conforme política.

## 5. Contexto ativo sem limite comercial de tokens

Memória total `M` pode crescer sem ser inserida integralmente no contexto ativo `B`.

Seleção:

```text
maximize Σ relevance_i * x_i
subject to Σ size_i * x_i <= B
           required_constraints ⊆ selected
           x_i ∈ {0,1}
```

O usuário nunca vê `B` como cota. O sistema preserva memória total e otimiza apenas a janela operacional.

## 6. Política de esclarecimento

O Guia pergunta quando o valor esperado de esclarecer supera a fricção:

```text
Ask if:
RiskWrong * ConsequenceWrong
  > FrictionAsk + DelayAsk
```

Pergunta é obrigatória nas fronteiras sensíveis listadas na seção 3, independentemente da confiança.

## 7. Contrato de colaboração

Vetor de preferências do usuário:

```text
W = [literalidade, humor, interrupção, correção,
     pressão, iniciativa, exploração, contenção, silêncio]
```

Atualizações materiais em `W` exigem consentimento. Inferências podem ser propostas:

```text
“Percebi que você prefere terminar o raciocínio antes das minhas perguntas.
Posso esperar uma pausa maior?”
```

Otimização conceitual:

```text
CollaborationQuality =
  (IntentPreservation + Progress + PsychologicalSafety)
  / (CognitiveFriction + UnwantedPressure + SemanticLoss)
```

Não transformar esta fórmula em diagnóstico clínico ou score oculto de pessoa.

## 8. Scheduler de produto

Cada task `i` possui:

```text
class_i
deadline_i?
estimated_work_i
memory_i
accelerator_i
cancellable_i
dependencies_i
```

Restrições duras:

- voz/barge-in não pode aguardar tarefa background longa;
- segurança e persistência não podem ser omitidas;
- renderer pode degradar fidelidade antes de degradar presença;
- task cancelada não consolida memória;
- sem starvation permanente.

Função prática:

```text
minimize
  α * response_latency
  + β * deadline_miss
  + γ * memory_pressure
  + δ * thermal_risk
  + ε * unnecessary_recompute
```

com segurança, integridade e intenção como restrições duras, nunca termos sacrificáveis.

## 9. Estimativa de duração

Após calibração local, cada operação tem vetor de trabalho `w` e a máquina capacidade estimada `c`.

Primeira estimativa:

```text
t_hat = setup + Σ_k (w_k / max(c_k, ε)) + queue_delay
```

Atualização online com média exponencial do erro:

```text
bias_(n+1) = λ*bias_n + (1-λ)*(t_real - t_hat)
t_corrected = max(0, t_hat + bias_(n+1))
```

Mostrar intervalo robusto baseado nos erros recentes, não precisão falsa:

> “Deve levar entre cinco e sete minutos.”

## 10. Conversa durante tarefas

Uma tarefa background publica eventos reais:

```text
STARTED
MILESTONE
NEEDS_DECISION
RECOVERABLE_ISSUE
READY_FOR_PREVIEW
COMPLETED
FAILED
```

O Guia pode conversar sobre itens não bloqueantes. Nunca inventa progresso. `NEEDS_DECISION` pausa apenas a ramificação afetada.

## 11. Voice duplex

Endpointing semântico combina:

- VAD;
- duração da pausa;
- estabilidade da transcrição parcial;
- completude sintática;
- prosódia quando disponível;
- padrão individual de pausas.

Uma unidade de fala consolida quando:

```text
P(end_of_thought | signals) >= θ_user
```

`θ_user` adapta-se com consentimento indireto operacional, mas não altera conteúdo ou perfil psicológico.

## 12. Proveniência

Cada decisão `d` mantém:

```text
Prov(d) = hash(
  source_events,
  interpretation,
  confirmation,
  base_version,
  resulting_delta
)
```

Eventos e artefatos usam serialização canônica. Hash protege integridade, não substitui assinatura ou criptografia.

## 13. Simulação

Uma simulação é tupla:

```text
Sim = (CreationVersion, Scenario, VirtualClock,
       FakeCapabilities, Seed, ExpectedInvariants)
```

Ela é aprovada quando:

- invariantes duras permanecem verdadeiras;
- não ocorre efeito real;
- comportamento observado corresponde ao contrato;
- replay determinístico coincide quando aplicável;
- diferenças não determinísticas ficam dentro do contrato declarado.

## 14. Inferência local

No bootstrap, modelos transformadores podem usar atenção padrão:

```text
Attention(Q,K,V) = softmax(QK^T / sqrt(d_k))V
```

O runtime deve suportar KV cache, quantização declarada e model card. Porém, a inteligência do Casulo não é reduzida ao LLM:

```text
I_Casulo = Model + Memory + Compiler + Tools + Verification + Relationship
```

## 15. Segurança por capabilities

Autorização:

```text
Allow(action) iff
  declared(action)
  and granted(capability(action))
  and policy_allows(context)
  and approval_satisfied(if required)
```

Negação é default. O modelo generativo não pode fabricar grants.

