# Especificacao da autoridade T de treinamento

## Cadeia vinculante

`human-confirmation-event -> confirmed_intent -> requirement_graph ->
training_authority_plan -> nove sources T/2.0 -> AST -> semantica -> typed IR ->
module graph -> bytecode estruturado -> TCAP -> runtime Rust -> receipt causal`.

Cada documento e selado por SHA-256 canonico e referencia o predecessor. O TCAP
preserva source, typed IR, bytecode, schemas, grafo, boundaries e proveniencia.
O verificador TCAP recompila a source e rejeita divergencia mesmo que um atacante
recalcule o manifesto.

## Superficies

1. `dataset_identity_integrity` compara o hash observado em runtime e as
   dimensoes;
2. `initialization_bundle` compara hash, unicidade de casos e nonces;
3. `numerical_precision` seleciona `float64` somente se a primitive declarar
   suporte;
4. `loss_function` seleciona `mse`;
5. `update_rule` seleciona `sgd` e `0.018`;
6. `optimizer_state` exige reset e ausencia de estado entre casos;
7. `working_set` seleciona todos os 1.024 registros;
8. `stopping` seleciona contagem fixa de 400 epocas e exige contador;
9. `equivalence_acceptance` fixa tolerancias e, depois do trabalho, julga a
   evidencia.

## Regra de consumo

O controller aceita somente um `Result ok` com mapa, validado pelo
`ProductiveTExecutor`. Nove outputs sao combinados sem colisao. Nao existe
default afirmativo. Falha de runtime, TCAP, hash, capability, input, receipt ou
surface interrompe antes da primitive.

O publicador futuro exige o receipt de `judgment::judge` encadeado ao nono
receipt de politica. Python pode validar o envelope, mas nao reconstruir
`PUBLISH`.

## Primitive estrangeira

A primitive executa algebra, alocacao e I/O. Sua manifestacao deve registrar
nome, versao, hash, ABI, tipos, precisao, efeitos e custo. Ela nao decide os nove
valores. Uma primitive pode recusar valor fora de sua ABI; nao pode substitui-lo.

## Limite de TI4

TI4 prova compilacao e consumo causal do plano antes de iniciar trabalho. A
autoridade completa continua pendente ate receipts internos do worker, nove
mutacoes, adversariais, juiz consumido e verificador independente.

