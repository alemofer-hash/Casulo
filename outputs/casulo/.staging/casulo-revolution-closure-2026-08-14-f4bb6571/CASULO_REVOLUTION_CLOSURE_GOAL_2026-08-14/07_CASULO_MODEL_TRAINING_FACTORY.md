# MOTOR E FÁBRICA DE TREINAMENTO CASULO

## 1. Decisão honesta de arquitetura

O arquivo `Qwen3-4B Q4_K_M.gguf` é artefato quantizado de inferência. Ele **não é
o checkpoint a ser treinado diretamente**. Um LoRA/QLoRA do Qwen3-4B exige o
checkpoint Hugging Face exato e compatível, tokenizer/template correspondentes,
framework de treino e hardware adequado.

No Machine Profile recebido — i5 de 12ª geração, 16 GiB de RAM, iGPU e uma GTX
1050 Ti de 4 GiB — treino 4B não deve ser presumido suportado ou reprodutível.
“Pode levar horas” não torna seguro um job que exige memória inexistente.

Portanto, este Goal separa:

```text
MANDATORY_LOCAL:
  dataset + lineage + evals + registry + adapter ABI
  treino real de especialista pequeno/roteador quando viável
  uso real desse especialista no Casulo

CONDITIONAL_4B:
  Guide LoRA/QLoRA no checkpoint Qwen3-4B
  somente com GPU/ambiente e espaço aprovados
```

O Goal nunca chama um smoke de 0.6B de “Qwen3-4B treinado”.

## 2. O que torna o motor first-party

```text
CasuloMotor = base bootstrap declarada
             + GuideContinuityKernel
             + memória/constraints
             + ContextAssembler
             + router/especialistas
             + adapters Casulo
             + T Forge/verificadores
             + sampling policies
             + TrainingFactory
```

Pesos fundacionais continuam atribuídos à origem. O diferencial próprio está na
arquitetura cognitiva, nos dados curados, nas adaptações e nos gates.

## 3. Model Registry

Cada entrada:

```text
model_id, role, architecture, upstream_id, upstream_commit,
base_hashes, tokenizer_hashes, chat_template_hash,
quantization, runtime_compatibility, license,
adapter_stack[], dataset_lineage[], eval_suite,
hardware_profile, promotion_state, signature, rollback_target
```

Estados:

```text
DISCOVERED -> QUARANTINED -> VERIFIED -> EXPERIMENTAL
-> CANDIDATE -> OWNER_PROMOTED
any -> REJECTED | REVOKED
```

## 4. Papéis neurais

- `DialogueGeneralist`: Qwen3-4B bootstrap para conversa e síntese;
- `GuideAdapter`: adaptação futura do tom/decisão, não memória pessoal;
- `TPlanningSpecialist`: modelo menor treinado em requirements/T/diagnostics;
- `SemanticRouter`: classificador/ranker first-party pequeno;
- `VerifierAssistant`: propõe obrigações/testes, sem autoridade de PASS;
- `UniverseAdapter`: opcional, somente quando um domínio provar necessidade.

Um especialista pequeno deve entrar apenas se melhora a rota sem piorar
latência/memória além do budget. Caso contrário, `REJECT` é sucesso de método.

## 5. Datasets

### Fontes permitidas

- specs, testes e diagnostics T first-party;
- sessões sintéticas geradas sob contratos;
- exemplos curados manualmente;
- preferências explícitas da prova/inspeção;
- artifacts próprios com provenance;
- fontes externas apenas com licença compatível e card.

### Proibido por padrão

- áudio bruto do usuário;
- conversas pessoais sem consentimento granular;
- secrets, credenciais, PII desnecessária;
- material sem licença/proveniência;
- outputs do holdout final;
- conteúdo public misturado com owner private.

### Famílias de registros

`guide_sft.jsonl`:

```json
{"example_id":"...","scenario_family_id":"...","messages":[],"mode":"EXPANSION","constraints":[],"provenance":{},"license":"..."}
```

`guide_preferences.jsonl`:

```json
{"pair_id":"...","prompt":[],"chosen":"...","rejected":"...","dimensions":{},"rater":"human|contract","provenance":{}}
```

`t_trajectories.jsonl`:

```json
{"task_id":"...","requirements":[],"candidate_t":"...","diagnostics":[],"repair":"...","evidence":[],"result":"PASS|FAIL"}
```

`router_examples.jsonl`:

```json
{"query":"...","allowed_universes":[],"required_capabilities":[],"chosen_route":[],"hard_negatives":[],"reason":"..."}
```

## 6. Split anticontaminação

Separar por `scenario_family_id`, projeto e estrutura de intenção — nunca apenas
por linha aleatória:

```text
train  = famílias A
valid  = famílias B
test   = famílias C
holdout_human = inexistente até a sessão de Guilherme
```

Executar deduplicação lexical/AST/semantic hash. Qualquer vizinhança suspeita
entre treino e test remove a família ou marca contaminação.

## 7. Etapas de treino

### TF0 — baseline

Congelar outputs, políticas de sampling, evals e rubrica antes de treinar.

### TF1 — SFT

Para sequências alvo `y`:

```text
L_SFT = - sum_t log p_theta(y_t | x, y_<t)
```

Treinar somente tokens do assistant/completion quando o framework permitir.

### TF2 — LoRA/QLoRA

```text
W' = W + (alpha/r) B A
```

Treinar matrizes de posto baixo; base permanece imutável. QLoRA usa base
quantizada durante treino, mas requer stack/hardware compatíveis — não o GGUF de
inferência como se fosse checkpoint treinável.

### TF3 — preferências, somente com dados suficientes

DPO para par `(y_w, y_l)`:

```text
L_DPO = -log sigma(beta[(log pi_theta(y_w|x)-log pi_ref(y_w|x))
                       -(log pi_theta(y_l|x)-log pi_ref(y_l|x))])
```

Não executar DPO sobre preferências sintéticas frágeis apenas para dizer que foi
feito. SFT + reranker pode ser a decisão correta desta etapa.

### TF4 — export e promoção

- exportar adapter separado;
- registrar hashes/card/licença;
- converter apenas por ferramenta pinada;
- testar contra runtime real;
- comparar base/adapter em holdout congelado;
- rollback instantâneo para base.

## 8. Objetivos e rubricas

Conceitualmente:

```text
L_total = lambda_d*L_dialogue
        + lambda_t*L_T
        + lambda_r*L_routing
        + lambda_c*L_constraints
        + lambda_s*L_safety
```

Na prática, trainers/papéis podem ser separados. Não somar losses incompatíveis
apenas na documentação.

Dimensões:

- continuidade e separação de projetos;
- detecção de contradição;
- valor das perguntas;
- não bajulação/não pressão;
- T parse/type/compile success;
- obligation recall e false completion;
- rota sem capability escalation;
- latência/footprint no Machine Profile.

## 9. Gate de promoção

Antes do treino, congelar `epsilon` por dimensão. Promover somente se:

```text
meaningful_gain >= epsilon_pre_registered
AND no hard_safety_regression
AND no mandatory_constraint_regression
AND runtime_compatibility == PASS
AND license_and_lineage == PASS
AND disk_and_memory_budget == PASS
```

Uma média global não pode esconder regressão crítica. Se falhar, manter a base e
registrar `ADAPTER_REJECTED_WITH_EVIDENCE`.

## 10. Caminho obrigatório na máquina recebida

1. doctor identifica CPU/GPU/RAM/driver/Python;
2. não instalar CUDA para GTX 1050 Ti presumindo viabilidade;
3. criar venv de treino isolada em Python suportado pelo lock;
4. validar pipeline com dataset minúsculo;
5. treinar `SemanticRouter` clássico/T-first ou `Qwen3-0.6B` LoRA pequeno,
   conforme footprint medido;
6. converter/servir como especialista opcional;
7. provar uma rota real e fallback;
8. não baixar checkpoint 4B de treino sem plano e consentimento.

## 11. Caminho condicional 4B

Requer, no mínimo, inventário que aprove:

- GPU NVIDIA suportada com VRAM suficiente (16 GiB mínimo experimental;
  24 GiB preferível) ou ambiente equivalente comprovado;
- RAM, armazenamento temporário e cooling;
- checkpoint exato com licença/hash;
- frameworks pinados;
- dados sanitizados;
- consentimento para qualquer compute externo;
- nenhum dado owner sensível enviado por padrão.

Se não houver:

```text
CASULO_4B_ADAPTER = DEFERRED_COMPUTE_NOT_AVAILABLE
```

O Goal pode ainda fechar o motor próprio no sentido arquitetural e com
especialista local real, mas deve preservar essa limitação na claim.

## 12. Referências técnicas a verificar na execução

- Qwen3 oficial: https://github.com/QwenLM/Qwen3
- llama.cpp/GBNF: https://github.com/ggml-org/llama.cpp/tree/master/grammars
- PEFT/LoRA: https://huggingface.co/docs/peft/main/conceptual_guides/lora
- PEFT quantization: https://huggingface.co/docs/peft/main/developer_guides/quantization
- TRL SFT: https://huggingface.co/docs/trl/en/sft_trainer
- TRL DPO: https://huggingface.co/docs/trl/en/dpo_trainer

Versões atuais devem ser resolvidas/pinadas pelo Codex; estes URLs não autorizam
instalação automática.

