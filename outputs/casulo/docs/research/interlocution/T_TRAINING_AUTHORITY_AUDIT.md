# Auditoria de autoridade T no treinamento — antes

## Metodo

Foi seguido o caminho real:

`flood_surrogate_training.t -> parser/AST -> semantica learn -> IR -> grafo ->
lower_learn_native -> TCAP -> worker Rust -> resultado -> receipts Python ->
equivalence Python`.

O full worker r2 teve 82/82 entradas do manifesto verificadas. A classificacao
abaixo aplica o gate binario do Goal: uma superficie so conta quando a decisao
esta na source T, atravessa o pipeline, e consumida antes do trabalho, possui
mutacao causal, receipt no ponto causal e julgamento consumido. Evidencia parcial
nao e arredondada para autoridade.

## Resultado

`A_T_before = 0/9 = 0.00`.

| Superficie | Fonte atual real | Evidencia T parcial | Lacuna que zera autoridade |
| --- | --- | --- | --- |
| dataset | `full_work_unit.py` gera dataset com `DATASET_SEED` e embute hash | T declara seed | T nao declara/decide o hash aceito; Python gera e sela |
| inicializacao | `build_initialization_payload` em Python | T declara um seed geral | bundle cientifico usa seeds e nonces Python distintos |
| precisao | T declara float64 e backend rejeita outra | AST/IR/grafo preservam precisao | contrato/worker tambem fixam float64 e nao ha receipt causal interno |
| loss | T declara MSE; backend so aceita MSE | `learn.loss` existe no IR/grafo | worker implementa MSE fixo; falta mutacao suportada e receipt interno |
| update | T declara SGD e learning rate | taxa chega ao plano e kernel valida bits | algoritmo/worker fixam SGD; recibo de decisao nao nasce no trabalho |
| optimizer state | criado por Torch/arrays do worker | nenhum | T nao governa reset/transicao/reuso |
| working set | full batch/RECORDS e constantes do worker | T declara `batch full` | selecao concreta e constante Python/Rust, sem politica causal T |
| stopping | T declara 400 epocas e target_loss | `learn.stop` existe no IR/grafo | worker usa contagem fixa; target nao julga parada; sem receipt T |
| equivalencia/aceitacao | `compare_results` e gate Python | resource contract carrega tolerancias | juiz nao e T e publicador nao consome decisao T |

## Descobertas estruturais

1. `build_full_work_unit_tcap` compila T corretamente, mas constroi dataset,
   inicializacoes e parte do contrato fora de T.
2. `_render_native_worker` fixa `RECORDS`, `EPOCHS` e `learning_rate=0.018` no
   wrapper Rust; o kernel tambem recebe/valida alguns desses valores.
3. Os contadores de epoca, forward, backward, step, visitas e escritas nascem no
   worker, o que e evidencia forte de trabalho integral.
4. `create_receipts` roda depois, em Python, sobre o arquivo de resultado. Esses
   receipts nao satisfazem a exigencia nova de receipt interno da decisao.
5. `compare_results` e `validate_receipts` sao o juiz atual em Python. Um
   resultado T nao e requerido para publicacao.
6. A trilha T/2.0 ja possui runtime Rust, TCAP com source/typed IR/bytecode e
   receipts causais de decisao. Ela pode ser reutilizada na pesquisa sem criar
   parser especial e sem afirmar que executa GEMM.

## Mapa de dados de `K` preservado

O runner solicita `K`, o worker executa o intervalo de casos, contadores internos
sao persistidos no resultado, e o runner cria exatamente `K` receipts. Isso
prova a unidade anterior, mas a nova trilha normalizara somente por receipts
internos aceitos pelo verificador independente.

## Correcao arquitetural proposta

Uma source T/2.0 compilada por `TcapV2Builder` decidira as nove superficies em
cadeia. Um controller de pesquisa somente transportara valores e executara a
primitive autorizada. Dataset e init serao content-addressed em runtime; o worker
emitira receipts internos; e um juiz T fail-closed autorizara publicacao. Python
nao reconstruira `PASS`.

## Auditoria posterior — instância implementada

Após TI3–TI7, as nove superfícies satisfazem o critério binário desta campanha:

| Superfície | Fonte T | Consumida antes | Mutação causal | Receipt | Juiz/publicador | Estado |
|---|---|---:|---:|---:|---:|---|
| dataset | `dataset_identity_integrity.t` | sim | hash adulterado recusado | sim | sim | T_AUTHORITY |
| inicialização | `initialization_bundle.t` | sim | bundle adulterado recusado | sim | sim | T_AUTHORITY |
| precisão | `numerical_precision.t` | sim | float32 altera contrato e primitive recusa | sim | sim | T_AUTHORITY |
| loss | `loss_function.t` | sim | MAE altera contrato e primitive recusa | sim | sim | T_AUTHORITY |
| update | `update_rule.t` | sim | LR 0,009 altera TCAP/config e primitive recusa | sim | sim | T_AUTHORITY |
| estado do otimizador | `optimizer_state.t` | sim | preservação entre casos recusada | sim | sim | T_AUTHORITY |
| working set | `working_set.t` | sim | 512 altera contrato e primitive recusa | sim | sim | T_AUTHORITY |
| stopping | `stopping.t` | sim | 399 altera contrato e primitive recusa | sim | sim | T_AUTHORITY |
| equivalência/aceitação | `equivalence_acceptance.t` | sim | juiz mutado nega publicação | sim | sim | T_AUTHORITY |

`A_T=9/9=1.00`. Isso é autoridade sobre decisões, não implementação T de GEMM,
PyTorch, NumPy, kernels, alocador ou hardware. O braço B prova que T pós-fato e
ignorada vale zero; o braço C prova que arquitetura T sem juiz consumido não
concede autoridade final.
