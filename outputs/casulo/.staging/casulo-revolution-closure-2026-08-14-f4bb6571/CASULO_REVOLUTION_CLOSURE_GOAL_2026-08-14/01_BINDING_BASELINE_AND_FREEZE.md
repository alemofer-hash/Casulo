# BASELINE VINCULANTE E CONGELAMENTO

## 1. Estado recebido

O estado narrado mais recente deve ser tratado como entrada a confirmar, não
como evidência substituta do repositório:

```text
product_alpha                    = PRODUCT_ALPHA_COMPLETE
generative_owner_G10             = 16/16 PASS
semantic_multiverse_reseal       = 29/29 PASS
current_human_state              = READY_FOR_GUILHERME_SEMANTIC_MULTIVERSE_REINSPECTION
human_reinspection_completed     = false_or_unconfirmed
cloud                            = RELEASE_LOCKED
usb_and_real_block_devices       = PROHIBITED
new_scientific_benchmark         = false
free_space_last_reported         ~= 82.46 GiB
```

Baseline neural recebido:

```text
model       = Qwen3-4B Q4_K_M
license     = Apache-2.0
sha256      = 7485fe6f...34fdf5   # confirmar valor completo na árvore
runtime     = llama.cpp b10362
license     = MIT
runtime_sha = 76008a26...9264e   # confirmar valor completo na árvore
```

Evidência Einstein recebida:

```text
claim = avaliador tensorial local 4D das equações de campo,
        parametrizável e validado para Minkowski no vácuo
global_PDE_solver = false
solver_sha256 = 609939f06313978c1b7768c84644d64918af2380b717faf2c047736e0fa9516d
minkowski_reproduction = PASS
empty_payload_refusal = PASS
invalid_json_refusal = PASS
```

O primeiro artefato Einstein genérico e a falha de renderer são fatos
históricos importantes: eles motivam o `SemanticFulfillmentGate`. Não apagar,
reescrever nem representar a primeira tentativa como solver correto.

## 2. Reconciliação antes de mutar

O Codex deve:

1. localizar a raiz real e ler integralmente todo `AGENTS.md` aplicável;
2. registrar branch, commit, status, submódulos, locks e não rastreados;
3. preservar o baseline Git histórico recebido (`df12e916...`, se confirmado);
4. localizar manifests G10/SM10/reseal e conferir hashes completos;
5. executar doctors read-only documentados;
6. registrar espaço livre e tamanho real de repo, pesos, caches, VM e overlays;
7. inventariar alterações do usuário sem adicioná-las ou descartá-las;
8. gerar `docs/product/RC_BASELINE_FREEZE.md` e manifest SHA-256;
9. criar branch/worktree isolado somente se a árvore permitir com segurança;
10. registrar explicitamente que a reinspeção humana anterior ainda não foi
    inventada como concluída.

## 3. Política de supersessão

Este Goal pode substituir a necessidade de uma reinspeção isolada pela prova
humana integrada final, desde que:

- o artefato resealed seja preservado;
- as regressões correspondentes continuem verdes;
- o estado histórico permaneça `REINSPECTION_PENDING`;
- nenhuma alegação diga que Guilherme aprovou o que não inspecionou;
- o novo handoff cubra, de forma mais ampla, os mesmos comportamentos.

## 4. Não regressões vinculantes

- owner é local, privado e offline no fluxo principal;
- public nunca contém motor, pesos, adapter, memória ou componentes owner;
- Cloud permanece fail-closed;
- output neural nunca concede capability;
- memória confirmada e restrições obrigatórias não podem ser sumarizadas fora;
- T Forge, compilação, simulação e publicação continuam transacionais;
- simulação não executa efeitos reais;
- materialização não contém secrets;
- base VM é imutável e overlay é descartável/restaurável;
- nenhum dispositivo físico é target;
- áudio bruto não persiste por padrão;
- assinatura de desenvolvimento não é chamada de assinatura comercial;
- nenhuma campanha de energia/superioridade é reiniciada.

## 5. Estados de divergência

Se o baseline não for confirmável, registrar exatamente um destes estados e
continuar apenas trabalho seguro independente:

```text
BLOCKED_BASELINE_DIVERGENCE
BLOCKED_ARTIFACT_INTEGRITY
BLOCKED_WORKTREE_COLLISION
```

É proibido fabricar hashes, regenerar evidência histórica e atribuir a ela a
data anterior, ou limpar o worktree para fazê-lo parecer simples.

