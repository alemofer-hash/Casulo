# GERAÇÃO GERAL E VERIFICAÇÃO SEMÂNTICA

## 1. Problema que este documento elimina

O pipeline Einstein mostrou duas verdades simultâneas:

1. o Casulo consegue gerar/reparar/materializar software inédito;
2. compilação e simulação genérica não provam que o software resolve o pedido.

Portanto:

```text
syntactic_success != semantic_fulfillment
```

## 2. `RequirementGraph`

Para uma criação, construa:

```text
R = (V, E)

r_i = (id, statement, kind, hardness, source, scope,
       dependencies, oracle, evidence, status, uncertainty)
```

Tipos mínimos:

- `BEHAVIOR`: o que deve fazer;
- `INPUT_OUTPUT`: contratos e formatos;
- `DOMAIN`: leis, unidades, invariantes e conhecimento;
- `SAFETY`: o que nunca pode fazer;
- `QUALITY`: tolerância, desempenho ou UX;
- `DEPLOYMENT`: onde deve funcionar;
- `OBSERVABILITY`: como provar e diagnosticar;
- `NON_GOAL`: fronteira explícita.

Estados:

```text
OPEN -> PROPOSED -> CONFIRMED -> IMPLEMENTED -> VERIFIED
                          \-> REJECTED
any -> BLOCKED_KNOWLEDGE | BLOCKED_TOOL | SUPERSEDED
```

## 3. Evidência e cobertura

Para cada requisito:

```text
e_i in [0,1]
w_i > 0
hard_i in {0,1}
```

Gap ponderado:

```text
SpecGap = sum_i w_i(1-e_i) / sum_i w_i
```

Promoção exige:

```text
forall i where hard_i=1: e_i = 1
AND SpecGap <= epsilon_creation
AND no unresolved contradiction
AND capability policy PASS
```

`e_i` não pode vir apenas de autoavaliação do mesmo modelo. Evidências válidas:

- type/schema/compile proof;
- teste determinístico;
- property/metamorphic test;
- static analysis;
- simulation receipt;
- domain equation/invariant check;
- execução em ambiente limpo;
- revisão humana marcada como tal.

## 4. Decomposição

`CreationDecomposer` transforma o pedido em:

```text
Goal
 -> capabilities
 -> components
 -> contracts
 -> failure modes
 -> verifiers
 -> deployment targets
```

O decompositor deve preservar wording e provenance do pedido original. Um
resumo nunca substitui o texto fonte. Mudança de escopo relevante gera
`IntentDelta.PROPOSED`.

## 5. Conhecimento especializado

Ordem de obtenção:

1. invariantes e bibliotecas locais verificadas;
2. `DomainPack` instalado, assinado e versionado;
3. derivação/implementação first-party com testes;
4. documento fornecido pelo usuário em quarentena e posteriormente validado;
5. declaração explícita de lacuna.

O owner offline não consulta a internet silenciosamente. Download/ingestão é
ação de desenvolvimento ou capability separada com consentimento, origem,
licença e hash.

`DomainPack` contém:

```text
domain_id, version, sources, licenses, invariants, units,
reference_algorithms, schemas, validators, goldens,
known_limits, prompt_injection_status, content_hash
```

## 6. Verificadores gerados com independência

O modelo pode propor testes, mas o gate exige diversidade de prova:

- pelo menos um verificador estrutural first-party;
- pelo menos um caso positivo;
- pelo menos um caso negativo/refusal;
- propriedades ou invariantes do domínio quando existirem;
- holdouts que não aparecem no contexto de geração;
- revisão contra requirement graph.

Evitar teste tautológico que apenas replica a implementação.

## 7. Reparo arquitetural

```text
candidate_k
 -> compile diagnostics
 -> requirement coverage
 -> domain invariants
 -> security/policy
 -> simulation
 -> clean execution
 -> GapReport_k
 -> RepairPlan_k
 -> candidate_(k+1)
```

`RepairPlan` pode:

- adicionar/remover componente;
- mudar interface ou algoritmo;
- introduzir domínio/verificador;
- dividir agente em serviços;
- reduzir escopo honestamente;
- corrigir T.

Budget por criação limita tentativas, tempo, memória e tamanho. Ao esgotar:

```text
status = PARTIAL_NOT_MATERIALIZABLE | PARTIAL_EXPORTABLE_DRAFT | REFUSED
```

Nunca “pronto” apenas porque o limite terminou.

## 8. Holdouts do Goal

Preparar famílias sem soluções no prompt, fixtures ou dataset de treino:

1. ferramenta de dados com parsing, validação e relatório;
2. automação local capability-scoped;
3. aplicação com UI e persistência;
4. agente multiuniverso envolvendo domínio técnico;
5. tarefa adversarial com requisito contraditório;
6. tarefa que excede capabilities e deve ser delimitada honestamente.

A criação de gate final é escolhida somente no momento da execução a partir de
uma ideia real de Guilherme; testes automatizados usam outros holdouts.

## 9. Gate contra o “Einstein genérico”

Para qualquer pedido que nomeie objetos/leis/algoritmos essenciais, o
`DomainCoverageScanner` verifica presença estrutural e comportamento. Exemplo:

```text
pedido: avaliar equações de campo de Einstein
obrigatório: métrica, derivadas/conexão, Ricci, escalar,
             tensor de Einstein, matéria/Lambda, resíduo, convenções
```

Um agente de memória que apenas menciona Einstein recebe cobertura zero nos
requisitos de domínio, mesmo que compile e materialize.

## 10. Produto, não campanha científica

Os ensaios deste Goal respondem:

- a criação cumpriu contratos?
- o usuário conseguiu corrigir?
- o artefato funcionou?
- o sistema explicou limites?

Não procuram recorde, paper, superioridade geral ou vantagem energética.

